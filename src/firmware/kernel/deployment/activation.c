#include "activation.h"
#include "image.h"
#include <string.h>
static int bank_or_none(uint32_t bank)
{
    return bank < 2 || bank == MICROS_ACTIVATION_NONE;
}
int micros_activation_valid(const micros_activation_record_t *record)
{
    return record->magic == MICROS_ACTIVATION_MAGIC && record->sequence &&
           record->commit == MICROS_ACTIVATION_COMMIT && bank_or_none(record->good) &&
           bank_or_none(record->previous) && bank_or_none(record->candidate) &&
           record->pending <= 1 && record->attempts <= MICROS_ACTIVATION_ATTEMPTS &&
           (!record->pending || (record->candidate < 2 && record->candidate != record->good)) &&
           (record->pending || record->candidate == MICROS_ACTIVATION_NONE) &&
           record->checksum ==
               micros_crc32((const void *)record, offsetof(micros_activation_record_t, checksum));
}
int micros_activation_latest(const micros_activation_record_t records[2])
{
    int first = micros_activation_valid(&records[0]), second = micros_activation_valid(&records[1]);
    if (!first && !second)
        return -1;
    return second && (!first || records[1].sequence > records[0].sequence) ? 1 : 0;
}
micros_activation_record_t micros_activation_empty(void)
{
    micros_activation_record_t record = {0};
    record.magic = MICROS_ACTIVATION_MAGIC;
    record.good = record.previous = record.candidate = MICROS_ACTIVATION_NONE;
    return record;
}
int micros_activation_seal(micros_activation_record_t *next, uint32_t previous_sequence)
{
    if (previous_sequence == UINT32_MAX)
        return 0;
    next->magic = MICROS_ACTIVATION_MAGIC;
    next->sequence = previous_sequence + 1;
    next->checksum =
        micros_crc32((const void *)next, offsetof(micros_activation_record_t, checksum));
    next->commit = MICROS_ACTIVATION_COMMIT;
    return micros_activation_valid(next);
}
uint32_t micros_activation_boot_bank(const micros_activation_record_t *record)
{
    return record->pending && record->attempts < MICROS_ACTIVATION_ATTEMPTS ? record->candidate
                                                                            : record->good;
}
