#include "support/storage.h"
#include "esp_partition.h"
#include "esp_system.h"
#include "image.h"
#include "mbedtls/sha256.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static const esp_partition_t *services_partition, *activation_partition;
static micros_activation_record_t selection;
static int selected_sector = -1;
static unsigned reset_boundary;
static unsigned mapped_users;
static int mapped_bank = -1;
static const void *mapped_code, *mapped_rodata;
static esp_partition_mmap_handle_t code_mapping, rodata_mapping;
int micros_storage_map_bank(unsigned bank, const void **code, const void **rodata)
{
    if (bank >= 2 || !services_partition || (mapped_users && mapped_bank != (int)bank))
        return 0;
    if (!mapped_users) {
        size_t offset = bank * MICROS_STORAGE_BANK_BYTES;
        if (esp_partition_mmap(services_partition, offset, MICROS_STORAGE_BANK_BYTES,
                               ESP_PARTITION_MMAP_INST, &mapped_code, &code_mapping) != ESP_OK)
            return 0;
        if (esp_partition_mmap(services_partition, offset, MICROS_STORAGE_BANK_BYTES,
                               ESP_PARTITION_MMAP_DATA, &mapped_rodata, &rodata_mapping) != ESP_OK) {
            esp_partition_munmap(code_mapping);
            return 0;
        }
        mapped_bank = bank;
    }
    ++mapped_users;
    *code = mapped_code;
    *rodata = mapped_rodata;
    return 1;
}
void micros_storage_unmap_bank(void)
{
    if (mapped_users && !--mapped_users) {
        esp_partition_munmap(code_mapping);
        esp_partition_munmap(rodata_mapping);
        mapped_bank = -1;
    }
}
int micros_storage_switch_bank(unsigned bank)
{
    if (bank >= 2) return 0;
    if (!mapped_users || mapped_bank == (int)bank) return 1;
    unsigned users = mapped_users, previous = (unsigned)mapped_bank;
    const void *expected_code = mapped_code, *expected_rodata = mapped_rodata;
    mapped_users = 1;
    micros_storage_unmap_bank();
    const void *code, *rodata;
    if (micros_storage_map_bank(bank, &code, &rodata)) {
        if (code == expected_code && rodata == expected_rodata) {
            mapped_users = users;
            return 1;
        }
        micros_storage_unmap_bank();
    }
    if (micros_storage_map_bank(previous, &code, &rodata)) {
        if (code == expected_code && rodata == expected_rodata) {
            mapped_users = users;
            return 0;
        }
        micros_storage_unmap_bank();
    }
    return -1;
}
void micros_storage_fault_arm(unsigned boundary)
{
    reset_boundary = boundary;
}
void micros_storage_fault_boundary(unsigned boundary)
{
    if (reset_boundary == boundary) {
        printf("FAULT reset boundary=%u\n", boundary);
        fflush(stdout);
        esp_restart();
    }
}
int micros_storage_init(void)
{
    services_partition =
        esp_partition_find_first(ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_ANY, "services");
    activation_partition =
        esp_partition_find_first(ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_ANY, "activation");
    if (!services_partition || services_partition->size < 2 * MICROS_STORAGE_BANK_BYTES ||
        !activation_partition || activation_partition->size != 2 * MICROS_STORAGE_SECTOR_BYTES)
        return 0;
    micros_activation_record_t sectors[2];
    for (unsigned index = 0; index < 2; ++index)
        if (esp_partition_read(activation_partition, index * MICROS_STORAGE_SECTOR_BYTES,
                               &sectors[index], sizeof(sectors[index])) != ESP_OK)
            return 0;
    selected_sector = micros_activation_latest(sectors);
    selection = selected_sector < 0 ? micros_activation_empty() : sectors[selected_sector];
    return 1;
}
static size_t image_offset(unsigned bank, unsigned slot)
{
    return bank * MICROS_STORAGE_BANK_BYTES + MICROS_STORAGE_SECTOR_BYTES +
           slot * MICROS_STORAGE_IMAGE_BYTES;
}
uint8_t *micros_storage_read_image(unsigned bank, unsigned slot, size_t *bytes)
{
    if (bank >= 2 || slot >= MICROS_BOARD_IMAGE_SLOTS || !bytes)
        return NULL;
    uint32_t header[16]; /* Native envelope is sixteen little-endian words. */
    size_t offset = image_offset(bank, slot);
    if (esp_partition_read(services_partition, offset, header, sizeof(header)) != ESP_OK ||
        header[0] != MICROS_IMAGE_MAGIC || header[7] > MICROS_BOARD_CODE_BYTES ||
        header[8] > MICROS_BOARD_DATA_BYTES)
        return NULL;
    *bytes = sizeof(header) + header[7] + header[8];
    uint8_t *image = malloc(*bytes);
    if (!image)
        return NULL;
    if (esp_partition_read(services_partition, offset, image, *bytes) != ESP_OK) {
        free(image);
        return NULL;
    }
    return image;
}
int micros_storage_write_image(unsigned bank, unsigned slot, const void *image, size_t bytes)
{
    if (bank >= 2 || slot >= MICROS_BOARD_IMAGE_SLOTS || (int)bank == mapped_bank || bank == selection.good ||
        selection.pending || bytes < MICROS_IMAGE_HEADER_BYTES || bytes > MICROS_BOARD_IMAGE_BYTES)
        return 0;
    size_t offset = image_offset(bank, slot);
    if (esp_partition_erase_range(services_partition, offset, MICROS_STORAGE_IMAGE_BYTES) != ESP_OK)
        return 0;
    micros_storage_fault_boundary(1); /* After inactive image erase. */
    size_t half = bytes / 2;
    if (esp_partition_write(services_partition, offset, image, half) != ESP_OK)
        return 0;
    micros_storage_fault_boundary(2); /* Torn inactive image. */
    if (esp_partition_write(services_partition, offset + half, (const uint8_t *)image + half,
                            bytes - half) != ESP_OK)
        return 0;
    micros_storage_fault_boundary(3); /* Complete image, no selected graph change. */
    return 1;
}
int micros_storage_read_graph(unsigned bank, micros_device_graph_t *graph)
{
    return bank < 2 && esp_partition_read(services_partition, bank * MICROS_STORAGE_BANK_BYTES,
                                          graph, sizeof(*graph)) == ESP_OK;
}
int micros_storage_write_graph(unsigned bank, const micros_device_graph_t *graph)
{
    if (bank >= 2 || (int)bank == mapped_bank || bank == selection.good || selection.pending)
        return 0;
    size_t offset = bank * MICROS_STORAGE_BANK_BYTES;
    if (esp_partition_erase_range(services_partition, offset, MICROS_STORAGE_SECTOR_BYTES) !=
        ESP_OK)
        return 0;
    micros_storage_fault_boundary(4); /* After inactive graph erase. */
    if (esp_partition_write(services_partition, offset, graph, sizeof(*graph)) != ESP_OK)
        return 0;
    micros_storage_fault_boundary(5); /* Complete graph, before trial selection. */
    return 1;
}
micros_activation_record_t micros_storage_selection(void)
{
    return selection;
}
int micros_storage_select(micros_activation_record_t next)
{
    if (!micros_activation_seal(&next, selection.sequence))
        return 0;
    unsigned destination = selected_sector == 0 ? 1 : 0;
    size_t offset = destination * MICROS_STORAGE_SECTOR_BYTES;
    if (esp_partition_erase_range(activation_partition, offset, MICROS_STORAGE_SECTOR_BYTES) !=
        ESP_OK)
        return 0;
    micros_storage_fault_boundary(6); /* Alternate journal erased; old record untouched. */
    size_t half = offsetof(micros_activation_record_t, commit) / 2;
    if (esp_partition_write(activation_partition, offset, &next, half) != ESP_OK)
        return 0;
    micros_storage_fault_boundary(7); /* Torn new record; no commit marker. */
    size_t payload = offsetof(micros_activation_record_t, commit);
    if (esp_partition_write(activation_partition, offset + half, (const uint8_t *)&next + half,
                            payload - half) != ESP_OK)
        return 0;
    micros_storage_fault_boundary(8); /* Full payload and CRC, marker still erased. */
    if (esp_partition_write(activation_partition, offset + payload, &next.commit,
                            sizeof(next.commit)) != ESP_OK)
        return 0;
    micros_storage_fault_boundary(9); /* New selection committed; reboot can reconstruct it. */
    micros_activation_record_t verified;
    if (esp_partition_read(activation_partition, offset, &verified, sizeof(verified)) != ESP_OK ||
        memcmp(&next, &verified, sizeof(next)) || !micros_activation_valid(&verified))
        return 0;
    selection = next;
    selected_sector = destination;
    return 1;
}

int micros_storage_image_path(unsigned bank, unsigned slot, char *path, size_t capacity)
{
    int n=snprintf(path,capacity,"/services/b%u-s%u.mimg",bank,slot);
    return bank<2 && slot<MICROS_BOARD_IMAGE_SLOTS && n>0 && (size_t)n<capacity;
}
int micros_storage_rebind_images(unsigned bank) { return micros_storage_switch_bank(bank); }

int micros_storage_prepare(unsigned bank) {
 return bank<2 && bank!=selection.good && !selection.pending && (int)bank!=mapped_bank &&
 esp_partition_erase_range(services_partition,bank*MICROS_STORAGE_BANK_BYTES,MICROS_STORAGE_BANK_BYTES)==ESP_OK;
}

int micros_storage_write_image_part(unsigned bank,unsigned slot,size_t offset,const void *data,size_t bytes) {
 return bank<2 && slot<4 && bank!=selection.good && !selection.pending && (int)bank!=mapped_bank &&
 offset<MICROS_BOARD_IMAGE_BYTES && bytes<=MICROS_BOARD_IMAGE_BYTES-offset &&
 esp_partition_write(services_partition,image_offset(bank,slot)+offset,data,bytes)==ESP_OK;
}

int micros_storage_read_image_part(unsigned bank,unsigned slot,size_t offset,void *output,size_t bytes) {
    return bank<2 && slot<4 && offset<=MICROS_BOARD_IMAGE_BYTES && bytes<=MICROS_BOARD_IMAGE_BYTES-offset &&
           esp_partition_read(services_partition,image_offset(bank,slot)+offset,output,bytes)==ESP_OK;
}
