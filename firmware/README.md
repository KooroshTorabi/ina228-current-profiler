# Firmware

- **[smart/](smart):** firmware for variant C (rev C board).
  - The on-board STM32G030 auto-ranges and serves one current value over I2C (0x48) and UART.
  - Includes host scripts for a Raspberry Pi or PC.
- **Variants A and B:** the logger MCU switches the ranges itself. The strategy is in [../docs/design.md](../docs/design.md#firmware-strategy-logger); the range logic in `smart/src/main.c` can be ported directly.
