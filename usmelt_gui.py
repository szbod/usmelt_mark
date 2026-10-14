import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import usmelt
import time
import configparser
import os
# Use SimpleAudio (aka py-simple-audio) instead of playsound on most platforms
# because playsound 1.3.0 fails to build its wheel on Python 3.12+
# (https://github.com/TaunoTakanen/PyPlaysound/issues/47).
# On macOS we keep playsound==1.2.2, which still works there and avoids
# SimpleAudio's seg fault reported in https://github.com/hamiltron/py-simple-audio/issues/72
import pathlib
import sys

if sys.platform == "darwin":
    import playsound as _playsound_module

    def play_sound(path):
        _playsound_module.playsound(str(path))
else:
    try:
        import simpleaudio as _simpleaudio

        def play_sound(path):
            wave_obj = _simpleaudio.WaveObject.from_wave_file(str(path))
            wave_obj.play()
    except ImportError:
        # No audio backend available; silently skip the sound effect.
        def play_sound(path):
            pass

class MelterApp:
    def __init__(self, master):
        self.master = master
        master.title("Melter Control")
        self.config = configparser.ConfigParser()
        self.config.read('usmelt.ini')

        try:
            self.find_and_init_pg()  # Initialize the pulse generator
        except Exception as e:
            messagebox.showerror("Device Error", f"Could not connect to device: {e}",icon='error')
            self.pg = None

        # --- Title Label ---
        self.title_label = ttk.Label(master, text="Melting laser (ch1)", font=("Helvetica", 10, "bold"))
        self.title_label.grid(row=0, column=0, columnspan=2, pady=10)

        self.title_label_ch2 = ttk.Label(master, text="Trigger laser (ch2)", font=("Helvetica", 10, "bold"))
        self.title_label_ch2.grid(row=0, column=2, columnspan=2, pady=10)

        # --- Enable Checkboxes ---
        self.enable_ch1_var = tk.BooleanVar(value=False)
        self.enable_ch1_check = ttk.Checkbutton(master, text="Enable", variable=self.enable_ch1_var, command=self.toggle_ch1_elements)
        self.enable_ch1_check.grid(row=1, column=0, columnspan=2, pady=5)

        self.enable_ch2_var = tk.BooleanVar(value=False)
        self.enable_ch2_check = ttk.Checkbutton(master, text="Enable", variable=self.enable_ch2_var, command=self.toggle_ch2_elements)
        self.enable_ch2_check.grid(row=1, column=2, columnspan=2, pady=5)



        # --- Menu Bar ---
        self.menubar = tk.Menu(master)
        self.settings_menu = tk.Menu(self.menubar, tearoff=0)
        self.settings_menu.add_command(label="Set Device...", command=self.set_device)
        self.melt_sound_var = tk.BooleanVar(value=self.config.getboolean('General', 'MeltSound', fallback=True))
        self.settings_menu.add_checkbutton(label="Melt sound", variable=self.melt_sound_var, command=self.save_settings)
        self.settings_menu.add_separator()
        self.settings_menu.add_command(label="Exit", command=master.quit)
        self.menubar.add_cascade(label="Settings", menu=self.settings_menu)
        master.config(menu=self.menubar)  # Add the menu bar to the window

        # --- Pulse Length ---
        self.pulse_length_label = ttk.Label(master, text="Pulse Length (µs):")
        self.pulse_length_label.grid(row=2, column=0, sticky="w", padx=5, pady=5)

        self.pulse_length_var = tk.StringVar(value="20")  # Default value
        self.pulse_length_entry = ttk.Entry(master, textvariable=self.pulse_length_var, width=10)
        self.pulse_length_entry.grid(row=2, column=1, sticky="e", padx=5, pady=5)
        self.pulse_length_entry.bind("<Return>", self.validate_inputs) # Validate on Enter key

        # --- Voltage High ---
        self.voltage_high_label = ttk.Label(master, text="Voltage High (V):")
        self.voltage_high_label.grid(row=3, column=0, sticky="w", padx=5, pady=5)

        self.voltage_high_var = tk.StringVar(value="5")  # Default value
        self.voltage_high_entry = ttk.Entry(master, textvariable=self.voltage_high_var, width=10)
        self.voltage_high_entry.grid(row=3, column=1, sticky="e", padx=5, pady=5)
        self.voltage_high_entry.bind("<Return>", self.validate_inputs) # Validate on Enter key

        # --- Delay ---
        self.delay_label = ttk.Label(master, text="Delay (µs):")
        self.delay_label.grid(row=4, column=0, sticky="w", padx=5, pady=5)

        self.delay_var = tk.StringVar(value="0")  # Default value
        self.delay_entry = ttk.Entry(master, textvariable=self.delay_var, width=10)
        self.delay_entry.grid(row=4, column=1, sticky="e", padx=5, pady=5)
        self.delay_entry.bind("<Return>", self.validate_inputs) # Validate on Enter key

        # --- Pulse Length (ch2) ---
        self.pulse_length_label_ch2 = ttk.Label(master, text="Pulse Length (µs):")
        self.pulse_length_label_ch2.grid(row=2, column=2, sticky="w", padx=5, pady=5)

        self.pulse_length_var_ch2 = tk.StringVar(value="20")  # Default value
        self.pulse_length_entry_ch2 = ttk.Entry(master, textvariable=self.pulse_length_var_ch2, width=10)
        self.pulse_length_entry_ch2.grid(row=2, column=3, sticky="e", padx=5, pady=5)
        self.pulse_length_entry_ch2.bind("<Return>", self.validate_inputs) # Validate on Enter key

        # --- Voltage High (ch2)---
        self.voltage_high_label_ch2 = ttk.Label(master, text="Voltage High (V):")
        self.voltage_high_label_ch2.grid(row=3, column=2, sticky="w", padx=5, pady=5)

        self.voltage_high_var_ch2 = tk.StringVar(value="5")  # Default value
        self.voltage_high_entry_ch2 = ttk.Entry(master, textvariable=self.voltage_high_var_ch2, width=10)
        self.voltage_high_entry_ch2.grid(row=3, column=3, sticky="e", padx=5, pady=5)
        self.voltage_high_entry_ch2.bind("<Return>", self.validate_inputs) # Validate on Enter key

        # --- Delay (ch2) ---
        self.delay_label_ch2 = ttk.Label(master, text="Delay (µs):")
        self.delay_label_ch2.grid(row=4, column=2, sticky="w", padx=5, pady=5)

        self.delay_var_ch2 = tk.StringVar(value="0")  # Default value
        self.delay_entry_ch2 = ttk.Entry(master, textvariable=self.delay_var_ch2, width=10)
        self.delay_entry_ch2.grid(row=4, column=3, sticky="e", padx=5, pady=5)
        self.delay_entry_ch2.bind("<Return>", self.validate_inputs)

        # --- Widget Groups ---
        self.ch1_widgets = [
            self.pulse_length_label, self.pulse_length_entry,
            self.voltage_high_label, self.voltage_high_entry,
            self.delay_label, self.delay_entry
        ]
        self.ch2_widgets = [
            self.pulse_length_label_ch2, self.pulse_length_entry_ch2,
            self.voltage_high_label_ch2, self.voltage_high_entry_ch2,
            self.delay_label_ch2, self.delay_entry_ch2
        ]

        # --- Melt Button ---
        self.melt_button = ttk.Button(master, text="Melt! (single pulse)", command=self.melt)
        self.melt_button.grid(row=5, column=0, columnspan=4, pady=10)

        self.toggle_ch1_elements()
        self.toggle_ch2_elements()


    def toggle_ch1_elements(self):
        """Enable or disable channel 1 widgets based on the checkbox."""
        state = "normal" if self.enable_ch1_var.get() else "disabled"
        for widget in self.ch1_widgets:
            widget.config(state=state)

    def toggle_ch2_elements(self):
        """Enable or disable channel 2 widgets based on the checkbox."""
        state = "normal" if self.enable_ch2_var.get() else "disabled"
        for widget in self.ch2_widgets:
            widget.config(state=state)

    def save_settings(self):
        """Saves settings to the INI file."""
        if not self.config.has_section('General'):
            self.config.add_section('General')
        self.config.set('General', 'MeltSound', str(self.melt_sound_var.get()))
        with open('usmelt.ini', 'w') as configfile:
            self.config.write(configfile)

    def find_and_init_pg(self):
        """Finds and initializes the pulse generator."""
        self.device_name = ""
        # First find the USB device that corresponds to the pulse generator
        device = usmelt.discover(['TG5012A'])
        self.device_name = device['TG5012A'].device  # Store the device name
        self.pg = usmelt.TG5012A(serial_port=self.device_name)
        self.init_pg()        

    def init_pg(self):
        # --- Channel 1 settings ---
        self.pg.channel(1)
        self.pg.wave('PULSE')
        self.pg.pulse_period(10e-3) # Short period for quick repetition
        self.pg.high(1) # Nominal high value
        self.pg.low(0)
        self.pg.pulse_rise(10e-9)
        self.pg.pulse_fall(10e-9)
        self.pg.pulse_delay(0)
        self.pg.burst("NCYC")
        self.pg.burst_count(1)
        self.pg.trigger_src("MAN")
        self.pg.output("OFF")

        # --- Channel 2 settings ---
        self.pg.channel(2)
        self.pg.wave('PULSE')
        self.pg.pulse_period(10e-3)
        self.pg.high(1)
        self.pg.low(0)
        self.pg.pulse_rise(10e-9)
        self.pg.pulse_fall(10e-9)
        self.pg.pulse_delay(0)
        self.pg.burst("NCYC")
        self.pg.burst_count(1)
        # Take trigger from channel 1
        self.pg.trigger_src("CRC")
        self.pg.output("OFF")

    def validate_inputs(self, event=None):
        """Validates all input fields for both channels."""
        try:
            # Channel 1 validation
            pulse_length1 = int(self.pulse_length_var.get())
            if pulse_length1 <= 0: raise ValueError("Pulse length (ch1) must be > 0.")
            voltage_high1 = float(self.voltage_high_var.get())
            if voltage_high1 <= 0: raise ValueError("Voltage (ch1) must be > 0.")
            delay1 = int(self.delay_var.get())
            if delay1 < 0: raise ValueError("Delay (ch1) must be >= 0.")

            # Channel 2 validation
            pulse_length2 = int(self.pulse_length_var_ch2.get())
            if pulse_length2 <= 0: raise ValueError("Pulse length (ch2) must be > 0.")
            voltage_high2 = float(self.voltage_high_var_ch2.get())
            if voltage_high2 <= 0: raise ValueError("Voltage (ch2) must be > 0.")
            delay2 = int(self.delay_var_ch2.get())
            if delay2 < 0: raise ValueError("Delay (ch2) must be >= 0.")

            ch1_params = (pulse_length1, voltage_high1, delay1)
            ch2_params = (pulse_length2, voltage_high2, delay2)
            return ch1_params, ch2_params

        except ValueError as e:
            messagebox.showerror("Input Error", str(e))
            return None, None

    def melt(self):
        """Handles the 'Melt!' button click."""
        if self.pg is None:
            messagebox.showerror("Device Error", "Pulse generator not initialized.")
            return        
        ch1_params, ch2_params = self.validate_inputs()
        if ch1_params and ch2_params:
            pulse_length1, voltage_high1, delay1 = ch1_params
            pulse_length2, voltage_high2, delay2 = ch2_params
            if self.enable_ch1_var.get():
                print(f"CH1: Pulse: {pulse_length1}µs, Voltage: {voltage_high1}V, Delay: {delay1}µs")
                # Set parameters for Channel 1
                self.pg.channel(1)
                self.pg.output("ON")
                self.pg.pulse_width(pulse_length1 * 1e-6)
                self.pg.high(voltage_high1)
                self.pg.pulse_delay(delay1 * 1e-6)
            else:
                self.pg.channel(1)
                self.pg.output("OFF")

            if self.enable_ch2_var.get():
                print(f"CH2: Pulse: {pulse_length2}µs, Voltage: {voltage_high2}V, Delay: {delay2}µs")
                # Set parameters for Channel 2
                self.pg.channel(2)
                self.pg.output("ON")
                self.pg.pulse_width(pulse_length2 * 1e-6)
                self.pg.high(voltage_high2)
                self.pg.pulse_delay(delay2 * 1e-6)
            else:            
                self.pg.channel(2)
                self.pg.output("OFF")

            # Trigger the pulse (assuming one trigger fires both channels)
            if self.enable_ch1_var.get() or self.enable_ch2_var.get():
                if self.melt_sound_var.get():
                    sound_effect_path = pathlib.Path(__file__).parent / 'sounds' / 'short-laser-sfx.wav'
                    play_sound(sound_effect_path)
                self.pg.channel(1)  # Trigger from channel 1, even if output is off
                self.pg.trigger()



    def set_device(self):
        """Opens a dialog to set the device name."""
        new_device = simpledialog.askstring(
            "Set Device", "Enter device name:", parent=self.master, initialvalue=self.device_name
        )
        if new_device is not None:  # Check if the user clicked Cancel
            self.device_name = new_device
            try:
                self.pg = usmelt.TG5012A(serial_port=new_device)
                self.init_pg()  # Re-initialize the pulse generator
            except Exception as e:
                messagebox.showerror("Device Error", f"Could not connect to device: {e}")
                self.pg = None


root = tk.Tk()
app = MelterApp(root)
root.mainloop()
