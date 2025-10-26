#!/usr/bin/env python3
# CS 350 Final Project – Smart Thermostat Prototype
# Features: AHT20 temp via I2C, state machine (OFF/HEAT/COOL),
# three buttons (mode/up/down), PWM LEDs, 16x2 I2C LCD, UART output every 30s.

import time
import math
import serial
from datetime import datetime
from gpiozero import PWMLED, Button
from smbus2 import SMBus, i2c_msg

# LCD (PCF8574 backpacks commonly at 0x27 or 0x3F)
LCD_ENABLED = True
try:
    from RPLCD.i2c import CharLCD
except Exception:
    LCD_ENABLED = False

# ========= PIN / HW CONFIG (adjust if needed) =========
# LEDs
RED_LED_PIN   = 18   # PWM-capable (heating indicator)
BLUE_LED_PIN  = 13   # PWM-capable (cooling indicator)

# Buttons
BTN_MODE_PIN  = 23   # first/green: cycles OFF→HEAT→COOL
BTN_UP_PIN    = 25   # raise setpoint by +1°F
BTN_DOWN_PIN  = 12   # lower setpoint by -1°F

# I2C – AHT20
I2C_BUS_NUM   = 1
AHT20_ADDR    = 0x38

# LCD – adjust address & cols/rows to your board
LCD_ADDR      = 0x27
LCD_COLS      = 16
LCD_ROWS      = 2

# UART
SERIAL_PORT   = "/dev/serial0"   # Pi alias to the enabled hardware UART
SERIAL_BAUD   = 115200
# ======================================================

# Defaults
SETPOINT_F_DEFAULT = 72
LCD_ALT_PERIOD     = 2.0      # seconds between the alternating 2nd line views
UART_PERIOD        = 30.0     # seconds between UART telemetry lines
FADE_TIME          = 1.0      # LED fade in/out seconds

# ----- State machine -----
OFF, HEAT, COOL = "off", "heat", "cool"
STATE_ORDER = [OFF, HEAT, COOL]

class Thermostat:
    def __init__(self):
        # LEDs
        self.red  = PWMLED(RED_LED_PIN,  initial_value=0.0)
        self.blue = PWMLED(BLUE_LED_PIN, initial_value=0.0)

        # Buttons
        self.btn_mode = Button(BTN_MODE_PIN, pull_up=True, bounce_time=0.08)
        self.btn_up   = Button(BTN_UP_PIN,   pull_up=True, bounce_time=0.08)
        self.btn_down = Button(BTN_DOWN_PIN, pull_up=True, bounce_time=0.08)

        # I2C bus
        self.bus = SMBus(I2C_BUS_NUM)

        # LCD
        self.lcd = None
        if LCD_ENABLED:
            try:
                self.lcd = CharLCD("PCF8574", LCD_ADDR, cols=LCD_COLS, rows=LCD_ROWS)
                self.lcd.clear()
            except Exception as e:
                print(f"[WARN] LCD init failed ({e}); continuing without LCD.")
                self.lcd = None

        # UART
        self.ser = None
        try:
            self.ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=1)
        except Exception as e:
            print(f"[WARN] UART init failed ({e}); continuing without UART.")

        # State
        self.state_idx = 0  # start at OFF
        self.setpoint_f = SETPOINT_F_DEFAULT
        self._last_uart = 0.0
        self._last_alt  = 0.0
        self._alt_flag  = False  # False: show temperature, True: show state+setpoint

        # Button handlers
        self.btn_mode.when_pressed = self._cycle_mode
        self.btn_up.when_pressed   = self._sp_up
        self.btn_down.when_pressed = self._sp_down

        # AHT20 initialization (soft reset + init)
        self._aht20_init()

    # ===== AHT20 helpers =====
    def _aht20_init(self):
        # Soft reset
        try:
            self.bus.write_byte(AHT20_ADDR, 0xBA)  # soft reset
            time.sleep(0.02)
        except Exception:
            pass  # some AHT20 clones ignore soft reset
        # Calibrate/initialize
        try:
            self.bus.write_i2c_block_data(AHT20_ADDR, 0xBE, [0x08, 0x00])
            time.sleep(0.01)
        except Exception as e:
            print(f"[WARN] AHT20 init step warning: {e}")

    def _aht20_read_celsius(self):
        """
        Trigger single measurement and read temp (°C).
        """
        # Trigger: 0xAC, 0x33, 0x00
        self.bus.write_i2c_block_data(AHT20_ADDR, 0xAC, [0x33, 0x00])
        time.sleep(0.08)  # datasheet: wait for measurement (typically 75ms)

        # Read 6 bytes
        read = i2c_msg.read(AHT20_ADDR, 6)
        self.bus.i2c_rdwr(read)
        data = list(read)

        if len(data) != 6:
            raise RuntimeError("AHT20: bad read length")

        # Byte0 status, then 5 bytes of measurement
        # Extract according to datasheet
        hum_raw = ((data[1] << 12) | (data[2] << 4) | (data[3] >> 4)) & 0xFFFFF
        tmp_raw = (((data[3] & 0x0F) << 16) | (data[4] << 8) | data[5]) & 0xFFFFF

        # Convert
        # humidity = hum_raw * 100.0 / 2^20
        temperature_c = (tmp_raw * 200.0 / (1 << 20)) - 50.0
        return temperature_c

    # ===== Buttons =====
    def _cycle_mode(self):
        self.state_idx = (self.state_idx + 1) % len(STATE_ORDER)
        print(f"[MODE] -> {self.state}")
        # stop any ongoing pulses to avoid overlap when changing modes
        self.red.stop(); self.blue.stop()
        self._apply_outputs(current_temp_f=None)  # refresh solid/off immediately

    def _sp_up(self):
        self.setpoint_f += 1
        print(f"[SETPOINT] {self.setpoint_f} F")

    def _sp_down(self):
        self.setpoint_f -= 1
        print(f"[SETPOINT] {self.setpoint_f} F")

    # ===== Properties =====
    @property
    def state(self):
        return STATE_ORDER[self.state_idx]

    # ===== Outputs / UI =====
    def _apply_outputs(self, current_temp_f):
        """
        Drives LEDs according to spec:
         - HEAT: below setpoint => red fades; else red solid
         - COOL: above setpoint => blue fades; else blue solid
         - OFF : both off
        """
        # If temperature not known (e.g., on mode change), just set solids/off by state
        if current_temp_f is None:
            if self.state == HEAT:
                self.red.value = 1.0; self.blue.off()
            elif self.state == COOL:
                self.blue.value = 1.0; self.red.off()
            else:
                self.red.off(); self.blue.off()
            return

        # Decide behavior
        self.red.stop(); self.blue.stop()  # cancel old pulses

        if self.state == HEAT:
            self.blue.off()
            if current_temp_f < self.setpoint_f:
                self.red.pulse(fade_in_time=FADE_TIME, fade_out_time=FADE_TIME, n=None, background=True)
            else:
                self.red.value = 1.0
        elif self.state == COOL:
            self.red.off()
            if current_temp_f > self.setpoint_f:
                self.blue.pulse(fade_in_time=FADE_TIME, fade_out_time=FADE_TIME, n=None, background=True)
            else:
                self.blue.value = 1.0
        else:  # OFF
            self.red.off(); self.blue.off()

    def _lcd_write(self, line1: str, line2: str):
        if not self.lcd:
            return
        # Ensure 16-char fit
        line1 = (line1[:LCD_COLS]).ljust(LCD_COLS)
        line2 = (line2[:LCD_COLS]).ljust(LCD_COLS)
        self.lcd.home()
        self.lcd.write_string(line1)
        self.lcd.crlf()
        self.lcd.write_string(line2)

    def _update_lcd(self, current_temp_f):
        # Line 1: date/time
        now = datetime.now().strftime("%m/%d %H:%M:%S")
        if not self._alt_flag:
            # show current temperature
            line2 = f"T:{current_temp_f:5.1f}F"
        else:
            # show state + setpoint
            st = {"off":"OFF","heat":"HEAT","cool":"COOL"}[self.state]
            line2 = f"{st} SP:{self.setpoint_f:>3d}F"
        self._lcd_write(now, line2)

    def _uart_send(self, current_temp_f):
        if not self.ser:
            return
        # "state,current_temp,set_temp"
        msg = f"{self.state},{current_temp_f:.1f},{self.setpoint_f}\n"
        try:
            self.ser.write(msg.encode("utf-8"))
        except Exception as e:
            print(f"[WARN] UART write failed: {e}")

    # ===== Main loop =====
    def run(self):
        print("[THERMOSTAT] starting… (Ctrl+C to exit)")
        try:
            while True:
                # Read temperature
                try:
                    temp_c = self._aht20_read_celsius()
                    temp_f = temp_c * 9.0/5.0 + 32.0
                except Exception as e:
                    print(f"[WARN] AHT20 read failed: {e}")
                    temp_f = float("nan")

                # Drive LEDs based on state & temp
                if not math.isnan(temp_f):
                    self._apply_outputs(temp_f)

                # Alternate LCD second line
                now = time.time()
                if now - self._last_alt >= LCD_ALT_PERIOD:
                    self._alt_flag = not self._alt_flag
                    self._last_alt = now
                if not math.isnan(temp_f):
                    self._update_lcd(temp_f)

                # UART every 30s
                if now - self._last_uart >= UART_PERIOD and not math.isnan(temp_f):
                    self._uart_send(temp_f)
                    self._last_uart = now

                time.sleep(0.05)
        except KeyboardInterrupt:
            pass
        finally:
            # Cleanup
            self.red.stop(); self.blue.stop()
            self.red.off();  self.blue.off()
            if self.lcd:
                try:
                    self.lcd.clear()
                except Exception:
                    pass
            if self.bus:
                try:
                    self.bus.close()
                except Exception:
                    pass
            if self.ser:
                try:
                    self.ser.close()
                except Exception:
                    pass
            print("[THERMOSTAT] stopped cleanly.")

if __name__ == "__main__":
    Thermostat().run()