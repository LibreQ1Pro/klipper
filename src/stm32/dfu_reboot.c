// Reboot into stm32 ROM dfu bootloader
//
// Copyright (C) 2019-2022  Kevin O'Connor <kevin@koconnor.net>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

#include <stddef.h> // size_t
#include "internal.h" // NVIC_SystemReset
#include "board/irq.h" // irq_disable
#include "compiler.h" // ARRAY_SIZE

// Many stm32 chips have a USB capable "DFU bootloader" in their ROM.
// In order to invoke that bootloader it is necessary to reset the
// chip and jump to a chip specific hardware address.
//
// To reset the chip, the dfu_reboot() code sets a flag in memory (at
// an arbitrary position that is unlikely to be overwritten during a
// chip reset), and resets the chip.  If dfu_reboot_check() sees that
// flag on the next boot it will perform a code jump to the ROM
// address.

// Location of ram address to set internal flag
#if CONFIG_MACH_STM32H7
  #define USB_BOOT_FLAG_ADDR (0x24000000 + 0x8000) // Place flag in "AXI SRAM"
#else
  #define USB_BOOT_FLAG_ADDR (CONFIG_RAM_START + CONFIG_RAM_SIZE - 1024)
#endif

// Signature to set in memory to flag that a dfu reboot is requested
#define USB_BOOT_FLAG 0x55534220424f4f54 // "USB BOOT"

#if CONFIG_STM32_SERIAL_ROM_BOOTLOADER || CONFIG_STM32_CHAINED_KATAPULT
// Return the chip to (mostly) its reset state so that other code can be
// started without a chip reset (a vendor bootloader at the start of flash
// would otherwise run first and could clear any request flags)
static void
reset_chip_state(void)
{
    irq_disable();
    // The watchdog can not be stopped - use its longest timeout (~32s)
    IWDG->KR = 0x5555;
    IWDG->PR = 6;
    IWDG->RLR = 0x0FFF;
    while (IWDG->SR)
        ;
    IWDG->KR = 0xAAAA;
    // Stop systick and disable all interrupts
    SysTick->CTRL = 0;
    for (int i = 0; i < ARRAY_SIZE(NVIC->ICER); i++) {
        NVIC->ICER[i] = 0xffffffff;
        NVIC->ICPR[i] = 0xffffffff;
    }
    // Run from the internal oscillator with the pll disabled
    RCC->CR |= RCC_CR_HSION;
    while (!(RCC->CR & RCC_CR_HSIRDY))
        ;
    RCC->CFGR = 0;
    while (RCC->CFGR & RCC_CFGR_SWS)
        ;
    RCC->CR &= ~(RCC_CR_PLLON | RCC_CR_HSEON);
    // Reset all peripherals
    RCC->AHB1RSTR = 0xffffffff;
    RCC->AHB1RSTR = 0;
    RCC->AHB2RSTR = 0xffffffff;
    RCC->AHB2RSTR = 0;
    RCC->APB1RSTR = 0xffffffff;
    RCC->APB1RSTR = 0;
    RCC->APB2RSTR = 0xffffffff;
    RCC->APB2RSTR = 0;
}

// Start the code with the given vector table
static void
jump_to_vectors(uint32_t *vectors)
{
    SCB->VTOR = (uint32_t)vectors;
    irq_enable();
    asm volatile("mov sp, %0\n bx %1"
                 : : "r"(vectors[0]), "r"(vectors[1]));
}
#endif

#if CONFIG_STM32_CHAINED_KATAPULT
// Katapult installed after a vendor bootloader (just before this code)
#define KATAPULT_ADDRESS (CONFIG_FLASH_APPLICATION_ADDRESS - 0x4000)
#define CANBOOT_SIGNATURE 0x21746f6f426e6143
#define CANBOOT_REQUEST   0x5984E3FA6CA1589B

static void
chained_katapult_request(void)
{
    uint32_t *bl_vectors = (uint32_t *)KATAPULT_ADDRESS;
    uint64_t *boot_sig = (uint64_t *)(bl_vectors[1] - 9);
    uint64_t *req_sig = (uint64_t *)bl_vectors[0];
    if (boot_sig != (void*)ALIGN((size_t)boot_sig, 8)
        || (uint32_t)boot_sig < KATAPULT_ADDRESS
        || (uint32_t)boot_sig >= CONFIG_FLASH_APPLICATION_ADDRESS
        || *boot_sig != CANBOOT_SIGNATURE
        || req_sig != (void*)ALIGN((size_t)req_sig, 8))
        // Katapult not found
        return;
    reset_chip_state();
    *req_sig = CANBOOT_REQUEST;
    jump_to_vectors(bl_vectors);
}
#endif

// Flag that bootloader is desired and reboot
void
dfu_reboot(void)
{
#if CONFIG_STM32_CHAINED_KATAPULT
    chained_katapult_request();
#endif
    if (!CONFIG_STM32_DFU_ROM_ADDRESS || !CONFIG_HAVE_BOOTLOADER_REQUEST)
        return;
#if CONFIG_STM32_SERIAL_ROM_BOOTLOADER
    // Map the ROM at address zero and jump to it
    reset_chip_state();
    RCC->APB2ENR |= RCC_APB2ENR_SYSCFGEN;
    SYSCFG->MEMRMP = SYSCFG_MEMRMP_MEM_MODE_0;
    jump_to_vectors((uint32_t*)CONFIG_STM32_DFU_ROM_ADDRESS);
#endif
    irq_disable();
    uint64_t *bflag = (void*)USB_BOOT_FLAG_ADDR;
    *bflag = USB_BOOT_FLAG;
#if __CORTEX_M >= 7
    SCB_CleanDCache_by_Addr((void*)bflag, sizeof(*bflag));
#endif
    NVIC_SystemReset();
}

// Check if rebooting into system DFU Bootloader
void
dfu_reboot_check(void)
{
    if (!CONFIG_STM32_DFU_ROM_ADDRESS || !CONFIG_HAVE_BOOTLOADER_REQUEST)
        return;
    if (*(uint64_t*)USB_BOOT_FLAG_ADDR != USB_BOOT_FLAG)
        return;
    *(uint64_t*)USB_BOOT_FLAG_ADDR = 0;
    uint32_t *sysbase = (uint32_t*)CONFIG_STM32_DFU_ROM_ADDRESS;
    asm volatile("mov sp, %0\n bx %1"
                 : : "r"(sysbase[0]), "r"(sysbase[1]));
}
