import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import usmelt
import time
import configparser
import os
import pathlib

# winsound only exists on Windows; on other platforms fall back to soundfile.
# (playsound was dropped because it fails to install on Python >= 3.12;
# simpleaudio is avoided due to missing wheels for modern Pythons and a
# reported segfault: https://github.com/hamiltron/py-simple-audio/issues/72)
try:
    import winsound
except ImportError:
    winsound = None
    try:
        import soundfile
    except ImportError:
        soundfile = None
import threading


def play_sound(path):
    """Play a sound file without blocking the GUI thread."""
    if winsound is not None:
        threading.Thread(
            target=winsound.PlaySound,
            args=(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC),
            daemon=True,
        ).start()
    elif soundfile is not None:
        data, samplerate = soundfile.read(str(path))
        soundfile.play(data, samplerate=samplerate, block=False)

class MelterApp:
    def __init__(self, master):
        self.master = master
        master.title("Melter Control")
        self.config = configparser.ConfigParser()
        self.config.read('usmelt.ini')

        # Load Pulse Shaping parameters
        self.use_shaping_var = tk.BooleanVar(value=self.config.getboolean('PulseShaping', 'UseShaping', fallback=False))
        self.shaping_v1 = tk.DoubleVar(value=self.config.getfloat('PulseShaping', 'V1', fallback=5.0))
        self.shaping_t1 = tk.DoubleVar(value=self.config.getfloat('PulseShaping', 'T1', fallback=10.0))
        self.shaping_v2 = tk.DoubleVar(value=self.config.getfloat('PulseShaping', 'V2', fallback=2.5))
        self.shaping_t2 = tk.DoubleVar(value=self.config.getfloat('PulseShaping', 'T2', fallback=10.0))

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
        self.ch2_widgets = [
            self.pulse_length_label_ch2, self.pulse_length_entry_ch2,
            self.voltage_high_label_ch2, self.voltage_high_entry_ch2,
            self.delay_label_ch2, self.delay_entry_ch2
        ]

        # --- Pulse Shaping widgets ---
        self.use_shaping_check = ttk.Checkbutton(
            master, text="Use Shaping", variable=self.use_shaping_var, command=self.on_shaping_toggled
        )
        self.use_shaping_check.grid(row=5, column=0, sticky="w", padx=5, pady=5)
        
        self.setup_shape_button = ttk.Button(
            master, text="Setup Shape...", command=self.open_shaping_dialog
        )
        self.setup_shape_button.grid(row=5, column=1, sticky="e", padx=5, pady=5)

        # --- Melt Button ---
        self.melt_button = ttk.Button(master, text="Melt! (single pulse)", command=self.melt)
        self.melt_button.grid(row=6, column=0, columnspan=4, pady=10)

        self.toggle_ch1_elements()
        self.toggle_ch2_elements()


    def on_shaping_toggled(self):
        self.toggle_ch1_elements()
        self.save_settings()

    def toggle_ch1_elements(self):
        """Enable or disable channel 1 widgets based on the checkbox and shaping state."""
        ch1_enabled = self.enable_ch1_var.get()
        shaping_enabled = self.use_shaping_var.get()
        
        main_state = "normal" if ch1_enabled else "disabled"
        shaping_state = "normal" if (ch1_enabled and shaping_enabled) else "disabled"
        standard_state = "normal" if (ch1_enabled and not shaping_enabled) else "disabled"
        
        # Configure standard widgets
        self.pulse_length_label.config(state=standard_state)
        self.pulse_length_entry.config(state=standard_state)
        self.voltage_high_label.config(state=standard_state)
        self.voltage_high_entry.config(state=standard_state)
        
        # Delay is always enabled when Ch 1 is enabled
        self.delay_label.config(state=main_state)
        self.delay_entry.config(state=main_state)
        
        # Shaping control widgets are enabled when Ch 1 is enabled
        self.use_shaping_check.config(state=main_state)
        self.setup_shape_button.config(state=main_state)

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
        
        if not self.config.has_section('PulseShaping'):
            self.config.add_section('PulseShaping')
        self.config.set('PulseShaping', 'UseShaping', str(self.use_shaping_var.get()))
        self.config.set('PulseShaping', 'V1', str(self.shaping_v1.get()))
        self.config.set('PulseShaping', 'T1', str(self.shaping_t1.get()))
        self.config.set('PulseShaping', 'V2', str(self.shaping_v2.get()))
        self.config.set('PulseShaping', 'T2', str(self.shaping_t2.get()))
        
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
        self.pg.burst("OFF")
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
        self.pg.burst("OFF")
        self.pg.burst_count(1)
        # Take trigger from channel 1
        self.pg.trigger_src("CRC")
        self.pg.output("OFF")

    def validate_inputs(self, event=None):
        """Validates all input fields for both channels."""
        try:
            # Channel 1 validation
            if self.use_shaping_var.get():
                pulse_length1 = 0.0
                voltage_high1 = 0.0
                delay1 = float(self.delay_var.get())
                if delay1 < 0: raise ValueError("Delay (ch1) must be >= 0.")
            else:
                pulse_length1 = float(self.pulse_length_var.get())
                if pulse_length1 <= 0: raise ValueError("Pulse length (ch1) must be > 0.")
                voltage_high1 = float(self.voltage_high_var.get())
                if voltage_high1 <= 0: raise ValueError("Voltage (ch1) must be > 0.")
                delay1 = float(self.delay_var.get())
                if delay1 < 0: raise ValueError("Delay (ch1) must be >= 0.")

            # Channel 2 validation
            pulse_length2 = float(self.pulse_length_var_ch2.get())
            if pulse_length2 <= 0: raise ValueError("Pulse length (ch2) must be > 0.")
            voltage_high2 = float(self.voltage_high_var_ch2.get())
            if voltage_high2 <= 0: raise ValueError("Voltage (ch2) must be > 0.")
            delay2 = float(self.delay_var_ch2.get())
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
                if self.use_shaping_var.get():
                    v1 = self.shaping_v1.get()
                    t1 = self.shaping_t1.get()
                    v2 = self.shaping_v2.get()
                    t2 = self.shaping_t2.get()
                    
                    t_tail = 10.0  # µs tail duration
                    t_total = delay1 + t1 + t2 + t_tail
                    
                    num_points = 10000
                    n_delay = int(round(num_points * delay1 / t_total))
                    n_t1 = int(round(num_points * t1 / t_total))
                    n_t2 = int(round(num_points * t2 / t_total))
                    n_tail = num_points - (n_delay + n_t1 + n_t2)
                    
                    # Ensure the first point is 0 and last point is 0. This will introduce tiny delay that should be irrelevant
                    voltages = [0.0] + [0.0] * n_delay + [v1] * n_t1 + [v2] * n_t2 + [0.0] * n_tail
                    
                    # Calculate scaling
                    vmin = min(0.0, v1, v2)
                    vmax = max(0.0, v1, v2)
                    vpp = vmax - vmin
                    if vpp < 0.01:
                        vpp = 0.01
                    voffset = (vmax + vmin) / 2.0
                    
                    # Scale to [0, 2^14 - 1]
                    points = []
                    for v in voltages:
                        y = int(round((2**14-1) * (v / vpp)))
                        y = max(0, min(2**14-1, y))
                        points.append(y)
 
                    print(f"CH1 (Shaping): V1: {v1}V for {t1}µs, V2: {v2}V for {t2}µs, Delay: {delay1}µs, Vpp: {vpp:.3f}V, Voffset: {voffset:.3f}V")
                    
                    # Program TG5012A for Channel 1
                    self.pg.channel(1)
                    self.pg.output_load(50)
                    self.pg.upload_arb("ARB1", points, interpolation="OFF")
                    self.pg.set("ARBLOAD", "ARB1")
                    self.pg.wave("ARB")
                    self.pg.offset(voffset)                    
                    self.pg.amplitude(vpp)
                    self.pg.period(t_total * 1e-6)
                    self.pg.burst("NCYC")   
                    self.pg.burst_count(1)
                    self.pg.trigger_src("MAN")                    
                    self.pg.output("ON")
                else:
                    print(f"CH1: Pulse: {pulse_length1}µs, Voltage: {voltage_high1}V, Delay: {delay1}µs")
                    # Set parameters for Channel 1
                    self.pg.channel(1)
                    self.pg.output_load(50)
                    self.pg.wave("PULSE")
                    self.pg.burst("NCYC")
                    self.pg.burst_count(1)
                    self.pg.trigger_src("MAN")                    
                    self.pg.pulse_width(pulse_length1 * 1e-6)
                    # The order between low and high matters! 
                    # If low is placed after you seem to get half the voltage
                    self.pg.low(0.0)                    
                    self.pg.high(voltage_high1)
                    self.pg.pulse_delay(delay1 * 1e-6)
                    self.pg.output("ON")                    
            else:
                self.pg.channel(1)
                self.pg.output("OFF")

            if self.enable_ch2_var.get():
                print(f"CH2: Pulse: {pulse_length2}µs, Voltage: {voltage_high2}V, Delay: {delay2}µs")
                # Set parameters for Channel 2
                self.pg.channel(2)
                self.pg.output_load(50)
                self.pg.wave("PULSE")
                self.pg.burst("NCYC")
                self.pg.burst_count(1)
                self.pg.trigger_src("CRC")
                self.pg.pulse_width(pulse_length2 * 1e-6)
                # The order between low and high matters! 
                # If low is placed after you seem to get half the voltage                
                self.pg.low(0.0)                
                self.pg.high(voltage_high2)
                self.pg.pulse_delay(delay2 * 1e-6)
                self.pg.output("ON")                
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
                
                # Disable the output after each pulse
                self.pg.channel(1)
                self.pg.output("OFF")
                self.pg.channel(2)
                self.pg.output("OFF")


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

    def open_shaping_dialog(self):
        """Opens the Pulse Shaping dialog to configure the two-step pulse waveform."""
        dialog = tk.Toplevel(self.master)
        dialog.title("Pulse Shaping Editor (ch1)")
        dialog.transient(self.master)
        dialog.grab_set()

        # Center the dialog relative to master window
        dialog.geometry("+%d+%d" % (self.master.winfo_rootx() + 50, self.master.winfo_rooty() + 50))
        dialog.resizable(False, False)

        # Temporary variables for dialog inputs
        v1_var = tk.StringVar(value=str(self.shaping_v1.get()))
        t1_var = tk.StringVar(value=str(self.shaping_t1.get()))
        v2_var = tk.StringVar(value=str(self.shaping_v2.get()))
        t2_var = tk.StringVar(value=str(self.shaping_t2.get()))

        # Layout Frames
        main_frame = ttk.Frame(dialog, padding="10")
        main_frame.pack(fill="both", expand=True)

        left_frame = ttk.LabelFrame(main_frame, text="Pulse Parameters", padding="10")
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))

        right_frame = ttk.LabelFrame(main_frame, text="Waveform Preview", padding="10")
        right_frame.pack(side="right", fill="both", expand=True)

        # Left entries
        ttk.Label(left_frame, text="Step 1 Voltage (V):").grid(row=0, column=0, sticky="w", pady=5)
        v1_entry = ttk.Entry(left_frame, textvariable=v1_var, width=10)
        v1_entry.grid(row=0, column=1, sticky="e", pady=5, padx=5)

        ttk.Label(left_frame, text="Step 1 Duration (µs):").grid(row=1, column=0, sticky="w", pady=5)
        t1_entry = ttk.Entry(left_frame, textvariable=t1_var, width=10)
        t1_entry.grid(row=1, column=1, sticky="e", pady=5, padx=5)

        ttk.Label(left_frame, text="Step 2 Voltage (V):").grid(row=2, column=0, sticky="w", pady=5)
        v2_entry = ttk.Entry(left_frame, textvariable=v2_var, width=10)
        v2_entry.grid(row=2, column=1, sticky="e", pady=5, padx=5)

        ttk.Label(left_frame, text="Step 2 Duration (µs):").grid(row=3, column=0, sticky="w", pady=5)
        t2_entry = ttk.Entry(left_frame, textvariable=t2_var, width=10)
        t2_entry.grid(row=3, column=1, sticky="e", pady=5, padx=5)

        # Canvas for preview
        canvas_width = 400
        canvas_height = 250
        canvas = tk.Canvas(right_frame, width=canvas_width, height=canvas_height, bg="white", highlightthickness=1, highlightbackground="#cccccc")
        canvas.pack(fill="both", expand=True)

        padding_x = 40
        padding_y = 35
        plot_w = canvas_width - 2 * padding_x
        plot_h = canvas_height - 2 * padding_y

        x_start = padding_x
        x_end = canvas_width - padding_x
        y_start = padding_y
        y_end = canvas_height - padding_y

        def update_plot(*args):
            try:
                v1_val = float(v1_var.get())
                t1_val = float(t1_var.get())
                v2_val = float(v2_var.get())
                t2_val = float(t2_var.get())
                if v1_val < 0 or v2_val < 0 or t1_val <= 0 or t2_val <= 0:
                    return
            except ValueError:
                # Keep current plot if user is in middle of typing an invalid float
                return

            try:
                delay_val = float(self.delay_var.get())
                if delay_val < 0:
                    delay_val = 0.0
            except ValueError:
                delay_val = 0.0

            canvas.delete("all")

            t_tail = 10.0
            t_total = delay_val + t1_val + t2_val + t_tail
            v_max = max(5.0, v1_val, v2_val)

            def to_coords(t, v):
                x = x_start + (t / t_total) * plot_w
                y = y_end - (v / v_max) * plot_h
                return x, y

            # Draw Y grid and labels
            for i in range(6):
                v_grid = (v_max / 5.0) * i
                _, gy = to_coords(0, v_grid)
                canvas.create_line(x_start, gy, x_end, gy, fill="#e0e0e0", dash=(2, 2))
                canvas.create_text(x_start - 8, gy, text=f"{v_grid:.1f}V", anchor="e", font=("Helvetica", 8), fill="#555555")

            # Draw X grid, ticks and labels (Timeline)
            abs_times = [0, delay_val, delay_val + t1_val, delay_val + t1_val + t2_val, t_total]
            labels = ["0", f"{delay_val:.1f}", f"+{t1_val:.1f}", f"+{t2_val:.1f}", f"{t_total:.1f}"]
            
            # Avoid overlaps on timeline text by deduplicating very close positions
            last_x = -999.0
            for t, label in zip(abs_times, labels):
                gx, gy = to_coords(t, 0)
                # Ticks
                canvas.create_line(gx, y_end, gx, y_end + 4, fill="#333333", width=1.5)
                # Vertical grid lines
                canvas.create_line(gx, y_start, gx, y_end, fill="#eaeaea", dash=(2, 2))
                
                # Make sure labels don't overlap
                if gx - last_x > 25:
                    canvas.create_text(gx, y_end + 12, text=label, anchor="n", font=("Helvetica", 8), fill="#555555")
                    last_x = gx

            # Axis labels
            canvas.create_text((x_start + x_end) / 2, y_end + 25, text="Time (µs)", anchor="n", font=("Helvetica", 9, "bold"), fill="#333333")
            canvas.create_text((x_start + x_end) / 2, y_start - 20, text="Laser Pulse Profile", anchor="n", font=("Helvetica", 10, "bold"), fill="#1a237e")

            # Waveform points
            pts = []
            pts.append(to_coords(0, 0))
            pts.append(to_coords(delay_val, 0))
            pts.append(to_coords(delay_val, v1_val))
            pts.append(to_coords(delay_val + t1_val, v1_val))
            pts.append(to_coords(delay_val + t1_val, v2_val))
            pts.append(to_coords(delay_val + t1_val + t2_val, v2_val))
            pts.append(to_coords(delay_val + t1_val + t2_val, 0))
            pts.append(to_coords(t_total, 0))

            flat_pts = []
            for px, py in pts:
                flat_pts.extend([px, py])

            # Draw filled blue area under curve
            canvas.create_polygon(flat_pts, fill="#e3f2fd", outline="")

            # Draw thick blue pulse path
            canvas.create_line(flat_pts, fill="#1976d2", width=3)

            # Axes
            canvas.create_line(x_start, y_end, x_end, y_end, fill="#333333", width=1.5)
            canvas.create_line(x_start, y_start, x_start, y_end, fill="#333333", width=1.5)

        # Bind traces for real-time canvas updates
        v1_var.trace_add("write", update_plot)
        t1_var.trace_add("write", update_plot)
        v2_var.trace_add("write", update_plot)
        t2_var.trace_add("write", update_plot)

        # Trigger initial plot drawing
        update_plot()

        # Action Buttons frame
        btn_frame = ttk.Frame(main_frame, padding=(0, 10, 0, 0))
        btn_frame.pack(fill="x", side="bottom")

        def on_ok():
            try:
                v1_val = float(v1_var.get())
                t1_val = float(t1_var.get())
                v2_val = float(v2_var.get())
                t2_val = float(t2_var.get())

                if v1_val < 0 or v2_val < 0:
                    raise ValueError("Voltages must be >= 0.")
                if t1_val <= 0 or t2_val <= 0:
                    raise ValueError("Durations must be > 0.")
            except ValueError as e:
                messagebox.showerror("Input Error", f"Please check your input values: {e}", parent=dialog)
                return

            # Save variables
            self.shaping_v1.set(v1_val)
            self.shaping_t1.set(t1_val)
            self.shaping_v2.set(v2_val)
            self.shaping_t2.set(t2_val)
            self.save_settings()
            dialog.destroy()

        def on_cancel():
            dialog.destroy()

        ok_button = ttk.Button(btn_frame, text="OK", command=on_ok)
        ok_button.pack(side="right", padx=5)

        cancel_button = ttk.Button(btn_frame, text="Cancel", command=on_cancel)
        cancel_button.pack(side="right")


root = tk.Tk()
app = MelterApp(root)
root.mainloop()
