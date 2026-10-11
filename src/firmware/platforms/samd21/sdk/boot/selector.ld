ENTRY(boot_start)
MEMORY { FLASH(rx) : ORIGIN = 0x2000, LENGTH = 0x1800
         RAM(rwx) : ORIGIN = 0x20000000, LENGTH = 0x8000 }
SECTIONS {
 .text : { KEEP(*(.vectors)) *(.text*) *(.rodata*) } > FLASH
 .data : { *(.data*) } > RAM AT> FLASH
 .bss (NOLOAD) : { *(.bss*) *(COMMON) } > RAM
 /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) }
}
ASSERT(SIZEOF(.data)==0 && SIZEOF(.bss)==0,"Selector must not depend on initialized globals")
