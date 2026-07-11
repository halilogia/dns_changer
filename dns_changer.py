import os
import sys
import ctypes
import socket
import time
import json
import threading
import subprocess
import re
import tkinter as tk
from tkinter import ttk, messagebox

# --- CONFIGURATION & STYLING ---
WINDOW_WIDTH = 560
WINDOW_HEIGHT = 730
FONT_TITLE = ("Segoe UI", 16, "bold")
FONT_SUBTITLE = ("Segoe UI", 9)
FONT_CARD_TITLE = ("Segoe UI", 10, "bold")
FONT_CARD_TEXT = ("Segoe UI", 9)
FONT_LATENCY = ("Segoe UI", 10, "bold")
FONT_BUTTON = ("Segoe UI", 10, "bold")

# Palette
COLOR_BG = "#0B0F19"          # Deep cosmic black-blue
COLOR_CARD = "#161D30"        # Card background
COLOR_CARD_SEL = "#232E4C"    # Selected card background
COLOR_ACCENT = "#6366F1"      # Indigo accent
COLOR_CYAN = "#06B6D4"        # Neon cyan for gaming/status
COLOR_GREEN = "#10B981"       # Success green
COLOR_RED = "#EF4444"         # Warning/Reset red
COLOR_TEXT_PRIMARY = "#F3F4F6"
COLOR_TEXT_MUTED = "#9CA3AF"
COLOR_BORDER = "#1E293B"      # Dark border
COLOR_BORDER_SEL = "#8B5CF6"  # Selected glowing border

# DNS Lists
POPULAR_DNS = [
    {
        "name": "Cloudflare DNS",
        "primary": "1.1.1.1",
        "secondary": "1.0.0.1",
        "desc": "Oyunlar için En İyi Gecikme ve Hız",
        "badge": "🎮 Oyun Önerisi",
        "badge_color": COLOR_CYAN
    },
    {
        "name": "Google DNS",
        "primary": "8.8.8.8",
        "secondary": "8.8.4.4",
        "desc": "Güvenilir, Hızlı ve Genel Kullanım",
        "badge": "⚡ Popüler",
        "badge_color": "#F59E0B" # Amber
    },
    {
        "name": "Quad9 Secure",
        "primary": "9.9.9.9",
        "secondary": "149.112.112.112",
        "desc": "Zararlı Yazılım ve Virüs Engelleme",
        "badge": "🛡️ Güvenli",
        "badge_color": COLOR_GREEN
    },
    {
        "name": "AdGuard DNS",
        "primary": "94.140.14.14",
        "secondary": "94.140.15.15",
        "desc": "Reklamları ve İzleyicileri Engeller",
        "badge": "🚫 Reklamsız",
        "badge_color": COLOR_RED
    },
    {
        "name": "OpenDNS Home",
        "primary": "208.67.222.222",
        "secondary": "208.67.220.220",
        "desc": "Aile Koruması ve Web Filtreleme",
        "badge": "👨‍👩‍👧 Aile",
        "badge_color": "#3B82F6" # Blue
    },
    {
        "name": "Level3 DNS",
        "primary": "4.2.2.1",
        "secondary": "4.2.2.2",
        "desc": "Küresel ve Köklü Altyapı",
        "badge": "🏢 Kurumsal",
        "badge_color": COLOR_TEXT_MUTED
    },
    {
        "name": "Özel DNS",
        "primary": "",
        "secondary": "",
        "desc": "Kendi tercih ettiğiniz DNS adreslerini girin",
        "badge": "✏️ Özelleştir",
        "badge_color": "#A855F7" # Purple
    }
]

# --- SYSTEM UTILITIES ---

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def run_as_admin():
    if not is_admin():
        # Relaunch the script as administrator
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, " ".join(sys.argv), None, 1
        )
        sys.exit(0)

def get_active_adapters():
    """Fetches list of active adapters using PowerShell"""
    cmd = ["powershell", "-NoProfile", "-Command", 
           "Get-NetAdapter | Where-Object {$_.Status -eq 'Up'} | Select-Object Name | ConvertTo-Json"]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            if isinstance(data, dict):
                return [data['Name']]
            elif isinstance(data, list):
                return [item['Name'] for item in data if 'Name' in item]
    except Exception:
        pass
    return ["Wi-Fi", "Ethernet"] # fallback defaults

def get_adapter_dns(adapter_name):
    """Gets currently configured DNS servers for the adapter"""
    cmd = ["powershell", "-NoProfile", "-Command",
           f"(Get-DnsClientServerAddress -InterfaceAlias '{adapter_name}' -AddressFamily IPv4).ServerAddresses"]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode == 0:
            dns_servers = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            return dns_servers
    except Exception:
        pass
    return []

def apply_dns_settings(adapter, dns_servers):
    """Applies the DNS settings to selected adapter (or all active adapters)"""
    adapters = get_active_adapters() if adapter == "Tüm Aktif Bağlantılar" else [adapter]
    errors = []
    
    for adj in adapters:
        if dns_servers:
            ips_str = ",".join(f"'{ip}'" for ip in dns_servers)
            cmd = ["powershell", "-NoProfile", "-Command",
                   f"Set-DnsClientServerAddress -InterfaceAlias '{adj}' -ServerAddresses ({ips_str})"]
        else:
            cmd = ["powershell", "-NoProfile", "-Command",
                   f"Set-DnsClientServerAddress -InterfaceAlias '{adj}' -ResetServerAddresses"]
        
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode != 0:
            errors.append(f"{adj}: {result.stderr.strip()}")
            
    return len(errors) == 0, errors

# --- DNS LATENCY TESTING ---

def measure_dns_latency(dns_ip, timeout=1.2):
    """Measures DNS lookup speed for google.com via UDP query, with standard ping fallback if blocked"""
    if not dns_ip:
        return None
        
    # Method 1: Raw DNS packet for A record query of google.com
    packet = bytearray([
        0x12, 0x34,  # Transaction ID
        0x01, 0x00,  # Flags: Standard query
        0x00, 0x01,  # Questions: 1
        0x00, 0x00,  # Answer RRs: 0
        0x00, 0x00,  # Authority RRs: 0
        0x00, 0x00,  # Additional RRs: 0
        # Query Name: google.com (6 'google' 3 'com' 0)
        0x06, 0x67, 0x6f, 0x6f, 0x67, 0x6c, 0x65,
        0x03, 0x63, 0x6f, 0x6d,
        0x00,        # Null label
        0x00, 0x01,  # Type: A
        0x00, 0x01   # Class: IN
    ])
    
    start = time.perf_counter()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(packet, (dns_ip, 53))
        data, addr = sock.recvfrom(512)
        end = time.perf_counter()
        if len(data) >= 2 and data[0] == 0x12 and data[1] == 0x34:
            return (end - start) * 1000  # returns in milliseconds
    except Exception:
        pass
        
    # Method 2: Fallback to system ping command if port 53 is blocked (common on school/corp/uni firewalls)
    try:
        # Request a single ping packet with timeout
        cmd = ["ping", "-n", "1", "-w", str(int(timeout * 1000)), dns_ip]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        if res.returncode == 0:
            match = re.search(r"time[=<](\d+)ms", res.stdout, re.IGNORECASE)
            if not match:
                # Localized OS check: support Turkish "süre" instead of "time"
                match = re.search(r"süre[=<](\d+)ms", res.stdout, re.IGNORECASE)
            if match:
                return float(match.group(1))
    except Exception:
        pass
        
    return None

# --- MODERN GUI APP ---

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Apex DNS Changer")
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.configure(bg=COLOR_BG)
        self.root.resizable(False, False)
        
        # Windows Icon Setup (Fallback to clean window)
        try:
            self.root.iconbitmap(default=None)
        except Exception:
            pass

        self.selected_index = 0
        self.latencies = [None] * len(POPULAR_DNS)
        self.fastest_index = None
        self.adapters = []
        self.current_adapter = tk.StringVar()
        
        # Custom elements
        self.card_widgets = []
        self.custom_primary_var = tk.StringVar()
        self.custom_secondary_var = tk.StringVar()
        
        self.build_ui()
        self.refresh_adapters()
        self.update_current_dns_display()
        
        # Auto-run speed test 500ms after startup
        self.root.after(500, self.start_speed_test)

    def build_ui(self):
        # 1. Header Frame
        header = tk.Frame(self.root, bg=COLOR_BG, pady=15, padx=25)
        header.pack(fill="x")
        
        title_label = tk.Label(header, text="APEX DNS CHANGER", font=FONT_TITLE, fg=COLOR_CYAN, bg=COLOR_BG)
        title_label.pack(anchor="w")
        
        sub_label = tk.Label(header, text="Kişisel bilgisayarınız için hızlı, güvenli ve kolay DNS yönetimi", font=FONT_SUBTITLE, fg=COLOR_TEXT_MUTED, bg=COLOR_BG)
        sub_label.pack(anchor="w", pady=(2, 0))
        
        # Separator line
        sep = tk.Frame(self.root, height=1, bg=COLOR_BORDER)
        sep.pack(fill="x", padx=25)

        # 2. Connection Settings (Adapter select + Info)
        conn_frame = tk.Frame(self.root, bg=COLOR_BG, padx=25, pady=12)
        conn_frame.pack(fill="x")
        
        tk.Label(conn_frame, text="Aktif Bağlantı:", font=FONT_CARD_TITLE, fg=COLOR_TEXT_PRIMARY, bg=COLOR_BG).grid(row=0, column=0, sticky="w", pady=5)
        
        self.adapter_menu = ttk.Combobox(conn_frame, textvariable=self.current_adapter, state="readonly", width=22)
        self.adapter_menu.grid(row=0, column=1, padx=10, sticky="w")
        self.adapter_menu.bind("<<ComboboxSelected>>", self.on_adapter_changed)
        
        self.active_dns_label = tk.Label(conn_frame, text="Mevcut DNS: Tespit ediliyor...", font=FONT_SUBTITLE, fg=COLOR_TEXT_MUTED, bg=COLOR_BG)
        self.active_dns_label.grid(row=0, column=2, padx=10, sticky="e")
        
        # 3. DNS List Scrollable Container
        list_container = tk.Frame(self.root, bg=COLOR_BG, padx=25)
        list_container.pack(fill="both", expand=True)
        
        self.list_canvas = tk.Canvas(list_container, bg=COLOR_BG, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(list_container, orient="vertical", command=self.list_canvas.yview)
        
        self.scroll_frame = tk.Frame(self.list_canvas, bg=COLOR_BG)
        self.scroll_frame.bind(
            "<Configure>",
            lambda e: self.list_canvas.configure(scrollregion=self.list_canvas.bbox("all"))
        )
        
        self.list_canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw", width=WINDOW_WIDTH-66)
        self.list_canvas.configure(yscrollcommand=self.scrollbar.set)
        
        self.list_canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y", padx=(5,0))
        
        # Populating list
        self.populate_dns_cards()
        
        # Custom DNS Entry Frame (hidden by default, packed below the cards)
        self.custom_entry_frame = tk.Frame(self.scroll_frame, bg=COLOR_CARD, bd=1, relief="flat", highlightbackground=COLOR_BORDER, highlightthickness=1)
        self.custom_entry_frame.pack(fill="x", pady=(5, 10), padx=2)
        self.custom_entry_frame.pack_forget() # Hide initially
        
        tk.Label(self.custom_entry_frame, text="Birincil DNS:", font=FONT_CARD_TEXT, fg=COLOR_TEXT_PRIMARY, bg=COLOR_CARD).grid(row=0, column=0, padx=15, pady=10, sticky="w")
        self.entry_prim = tk.Entry(self.custom_entry_frame, textvariable=self.custom_primary_var, bg=COLOR_BG, fg=COLOR_TEXT_PRIMARY, insertbackground=COLOR_TEXT_PRIMARY, bd=0, highlightthickness=1, highlightbackground=COLOR_BORDER, highlightcolor=COLOR_ACCENT, width=16)
        self.entry_prim.grid(row=0, column=1, padx=5, pady=10)
        
        tk.Label(self.custom_entry_frame, text="İkincil DNS:", font=FONT_CARD_TEXT, fg=COLOR_TEXT_PRIMARY, bg=COLOR_CARD).grid(row=0, column=2, padx=15, pady=10, sticky="w")
        self.entry_sec = tk.Entry(self.custom_entry_frame, textvariable=self.custom_secondary_var, bg=COLOR_BG, fg=COLOR_TEXT_PRIMARY, insertbackground=COLOR_TEXT_PRIMARY, bd=0, highlightthickness=1, highlightbackground=COLOR_BORDER, highlightcolor=COLOR_ACCENT, width=16)
        self.entry_sec.grid(row=0, column=3, padx=5, pady=10)
        
        # Bind custom inputs to update data
        self.custom_primary_var.trace_add("write", self.on_custom_dns_typed)
        self.custom_secondary_var.trace_add("write", self.on_custom_dns_typed)

        # 4. Action Buttons Footer Frame
        footer = tk.Frame(self.root, bg=COLOR_BG, pady=18, padx=25)
        footer.pack(fill="x", side="bottom")
        
        # Progress status text for tests
        self.status_text = tk.Label(footer, text="DNS hız testleri ölçülüyor, lütfen bekleyin...", font=FONT_SUBTITLE, fg=COLOR_TEXT_MUTED, bg=COLOR_BG)
        self.status_text.pack(anchor="w", pady=(0, 10))
        
        btn_frame = tk.Frame(footer, bg=COLOR_BG)
        btn_frame.pack(fill="x")
        
        # Modern Styled Flat Buttons
        # Speed test button
        self.btn_speed = tk.Button(
            btn_frame, text="⚡ HIZ TESTİ YAP", font=FONT_BUTTON, fg=COLOR_CYAN, bg=COLOR_CARD,
            activeforeground=COLOR_CYAN, activebackground=COLOR_CARD_SEL, bd=0, padx=15, pady=10,
            cursor="hand2", relief="flat", command=self.start_speed_test
        )
        self.btn_speed.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        
        # Reset button
        self.btn_reset = tk.Button(
            btn_frame, text="🔄 DHCP (VARSAYILAN)", font=FONT_BUTTON, fg=COLOR_RED, bg=COLOR_CARD,
            activeforeground=COLOR_RED, activebackground=COLOR_CARD_SEL, bd=0, padx=15, pady=10,
            cursor="hand2", relief="flat", command=self.reset_dns
        )
        self.btn_reset.grid(row=0, column=1, sticky="ew", padx=5)
        
        # Apply button
        self.btn_apply = tk.Button(
            btn_frame, text="✅ DNS UYGULA", font=FONT_BUTTON, fg=COLOR_TEXT_PRIMARY, bg=COLOR_ACCENT,
            activeforeground=COLOR_TEXT_PRIMARY, activebackground="#4F46E5", bd=0, padx=20, pady=10,
            cursor="hand2", relief="flat", command=self.apply_dns
        )
        self.btn_apply.grid(row=0, column=2, sticky="ew", padx=(5, 0))
        
        btn_frame.columnconfigure(0, weight=1)
        btn_frame.columnconfigure(1, weight=1)
        btn_frame.columnconfigure(2, weight=1)

    def populate_dns_cards(self):
        for index, item in enumerate(POPULAR_DNS):
            card = tk.Frame(self.scroll_frame, bg=COLOR_CARD, bd=1, relief="flat", highlightbackground=COLOR_BORDER, highlightthickness=1, cursor="hand2")
            card.pack(fill="x", pady=4, padx=2)
            
            # Left Selection Indicator Dot
            sel_indicator = tk.Canvas(card, width=12, height=12, bg=COLOR_CARD, highlightthickness=0)
            sel_indicator.pack(side="left", padx=(15, 10))
            
            # Content Frame (Title + Subtext)
            content = tk.Frame(card, bg=COLOR_CARD)
            content.pack(side="left", fill="y", pady=10)
            
            # Row 1: Title + Badge
            title_row = tk.Frame(content, bg=COLOR_CARD)
            title_row.pack(anchor="w")
            
            lbl_title = tk.Label(title_row, text=item["name"], font=FONT_CARD_TITLE, fg=COLOR_TEXT_PRIMARY, bg=COLOR_CARD)
            lbl_title.pack(side="left")
            
            if item.get("badge"):
                lbl_badge = tk.Label(title_row, text=f"  {item['badge']}  ", font=("Segoe UI", 8, "bold"), fg=item["badge_color"], bg="#1E293B", bd=0)
                lbl_badge.pack(side="left", padx=10)
            
            # Row 2: Description
            lbl_desc = tk.Label(content, text=item["desc"], font=FONT_CARD_TEXT, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD)
            lbl_desc.pack(anchor="w", pady=(2, 0))
            
            # Row 3: IPs
            ips_text = f"{item['primary']}  |  {item['secondary']}" if item["primary"] else "DNS Adreslerini manuel girin"
            lbl_ips = tk.Label(content, text=ips_text, font=("Consolas", 9), fg=COLOR_CYAN if item["name"] == "Cloudflare DNS" else COLOR_TEXT_MUTED, bg=COLOR_CARD)
            lbl_ips.pack(anchor="w", pady=(2, 0))
            
            # Right End: Ping/Latency text + Stars
            right_frame = tk.Frame(card, bg=COLOR_CARD)
            right_frame.pack(side="right", padx=(0, 20), fill="y")
            
            lbl_ping = tk.Label(right_frame, text="-- ms", font=FONT_LATENCY, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD)
            lbl_ping.pack(side="top", anchor="e", pady=(10, 0))
            
            lbl_star = tk.Label(right_frame, text="", font=("Segoe UI", 12, "bold"), fg="#F59E0B", bg=COLOR_CARD)
            lbl_star.pack(side="top", anchor="e")

            # Store references to update them dynamically
            self.card_widgets.append({
                "frame": card,
                "indicator": sel_indicator,
                "title": lbl_title,
                "desc": lbl_desc,
                "ips": lbl_ips,
                "ping": lbl_ping,
                "star": lbl_star,
                "content_frame": content,
                "title_row": title_row,
                "right_frame": right_frame
            })
            
            # Bind click events to select the card
            for w in (card, content, title_row, lbl_title, lbl_desc, lbl_ips, right_frame, lbl_ping, lbl_star):
                w.bind("<Button-1>", lambda event, idx=index: self.select_card(idx))

        self.update_card_visuals()

    def select_card(self, index):
        self.selected_index = index
        self.update_card_visuals()
        
        # Show/Hide Custom Entry Frame
        if POPULAR_DNS[index]["name"] == "Özel DNS":
            self.custom_entry_frame.pack(fill="x", pady=(5, 10), padx=2)
            self.entry_prim.focus()
        else:
            self.custom_entry_frame.pack_forget()

    def update_card_visuals(self):
        for index, item in enumerate(self.card_widgets):
            is_sel = (index == self.selected_index)
            bg_color = COLOR_CARD_SEL if is_sel else COLOR_CARD
            border_color = COLOR_BORDER_SEL if is_sel else COLOR_BORDER
            
            # Update Frame background & Border Glow
            item["frame"].configure(bg=bg_color, highlightbackground=border_color)
            item["content_frame"].configure(bg=bg_color)
            item["title_row"].configure(bg=bg_color)
            item["title"].configure(bg=bg_color)
            item["desc"].configure(bg=bg_color)
            item["ips"].configure(bg=bg_color)
            item["right_frame"].configure(bg=bg_color)
            item["ping"].configure(bg=bg_color)
            item["star"].configure(bg=bg_color)
            item["indicator"].configure(bg=bg_color)
            
            # Draw custom Selection Dot
            item["indicator"].delete("all")
            if is_sel:
                # Glowing indicator ring
                item["indicator"].create_oval(1, 1, 11, 11, outline=COLOR_BORDER_SEL, width=2)
                item["indicator"].create_oval(3, 3, 9, 9, fill=COLOR_BORDER_SEL, outline="")
            else:
                # Dim placeholder ring
                item["indicator"].create_oval(1, 1, 11, 11, outline=COLOR_BORDER, width=2)

    def on_custom_dns_typed(self, *args):
        # Update Özel DNS dictionary values on keyboard input
        prim = self.custom_primary_var.get().strip()
        sec = self.custom_secondary_var.get().strip()
        POPULAR_DNS[-1]["primary"] = prim
        POPULAR_DNS[-1]["secondary"] = sec
        
        if prim:
            self.card_widgets[-1]["ips"].configure(text=f"{prim}  |  {sec if sec else 'Otomatik'}", fg=COLOR_TEXT_PRIMARY)
        else:
            self.card_widgets[-1]["ips"].configure(text="DNS Adreslerini manuel girin", fg=COLOR_TEXT_MUTED)

    # --- ACTION HANDLERS ---

    def refresh_adapters(self):
        self.adapters = get_active_adapters()
        menu_items = self.adapters.copy()
        if len(menu_items) > 1:
            menu_items.append("Tüm Aktif Bağlantılar")
            
        self.adapter_menu["values"] = menu_items
        if menu_items:
            self.current_adapter.set(menu_items[0])
            self.on_adapter_changed()

    def on_adapter_changed(self, event=None):
        self.update_current_dns_display()

    def update_current_dns_display(self):
        adapter = self.current_adapter.get()
        if not adapter:
            return
        
        if adapter == "Tüm Aktif Bağlantılar":
            self.active_dns_label.configure(text="Mevcut DNS: Çoklu Seçim", fg=COLOR_TEXT_MUTED)
            return
            
        dns_servers = get_adapter_dns(adapter)
        if dns_servers:
            dns_str = ", ".join(dns_servers)
            self.active_dns_label.configure(text=f"Mevcut DNS: {dns_str}", fg=COLOR_GREEN)
        else:
            self.active_dns_label.configure(text="Mevcut DNS: Otomatik (DHCP)", fg=COLOR_TEXT_MUTED)

    def start_speed_test(self):
        # Disable buttons during execution
        self.btn_speed.configure(state="disabled", fg=COLOR_TEXT_MUTED)
        self.status_text.configure(text="DNS hız testi başlatıldı, sorgular yapılıyor...", fg=COLOR_CYAN)
        
        # Clear previous stars
        for item in self.card_widgets:
            item["star"].configure(text="")
            item["ping"].configure(text="Ölçülüyor...", fg=COLOR_TEXT_MUTED)
            
        self.root.update_idletasks()
        
        # Run test thread
        threading.Thread(target=self.run_speed_tests_thread).start()

    def run_speed_tests_thread(self):
        results = {}
        threads = []
        
        def worker(index, ip):
            lat = measure_dns_latency(ip)
            results[index] = lat

        for index, item in enumerate(POPULAR_DNS):
            # If Özel DNS is selected but empty, skip it
            if item["name"] == "Özel DNS" and not item["primary"]:
                results[index] = None
                continue
                
            ip_to_test = item["primary"]
            t = threading.Thread(target=worker, args=(index, ip_to_test))
            threads.append(t)
            t.start()
            
        for t in threads:
            t.join()
            
        # Post results to GUI safely
        self.root.after(0, lambda: self.process_test_results(results))

    def process_test_results(self, results):
        self.btn_speed.configure(state="normal", fg=COLOR_CYAN)
        
        min_lat = float('inf')
        self.fastest_index = None
        
        for index, lat in results.items():
            self.latencies[index] = lat
            ping_label = self.card_widgets[index]["ping"]
            
            if lat is not None:
                ping_label.configure(text=f"{int(lat)} ms", fg=COLOR_GREEN if lat < 30 else (COLOR_CYAN if lat < 60 else COLOR_TEXT_MUTED))
                
                # Check for fastest (exclude Custom if we wish, or keep it. Let's keep it if valid)
                if lat < min_lat:
                    min_lat = lat
                    self.fastest_index = index
            else:
                ping_label.configure(text="Zaman Aşımı", fg=COLOR_RED)
                
        # Draw star next to fastest
        if self.fastest_index is not None:
            self.card_widgets[self.fastest_index]["star"].configure(text="⭐ En Hızlı")
            fastest_dns_name = POPULAR_DNS[self.fastest_index]["name"]
            self.status_text.configure(text=f"Test tamamlandı. Mevcut bağlantınız için en hızlı DNS: {fastest_dns_name} ({int(min_lat)} ms)", fg=COLOR_GREEN)
        else:
            self.status_text.configure(text="Hız testi tamamlandı. Bazı sunucular yanıt vermedi.", fg=COLOR_RED)
            
        self.update_card_visuals()

    def apply_dns(self):
        adapter = self.current_adapter.get()
        if not adapter:
            messagebox.showerror("Hata", "Lütfen bir ağ adaptörü seçin!")
            return
            
        dns_config = POPULAR_DNS[self.selected_index]
        prim = dns_config["primary"]
        sec = dns_config["secondary"]
        
        if dns_config["name"] == "Özel DNS":
            if not prim:
                messagebox.showerror("Hata", "Lütfen geçerli bir birincil Özel DNS adresi girin!")
                return
                
        # Check IP validity (simple check)
        def is_valid_ip(ip):
            try:
                socket.inet_aton(ip)
                return True
            except socket.error:
                return False
                
        if not is_valid_ip(prim):
            messagebox.showerror("Hata", f"Geçersiz IP adresi: {prim}")
            return
            
        if sec and not is_valid_ip(sec):
            messagebox.showerror("Hata", f"Geçersiz ikincil IP adresi: {sec}")
            return

        self.status_text.configure(text="Yeni DNS ayarları uygulanıyor...", fg=COLOR_CYAN)
        self.root.update_idletasks()
        
        servers = [prim]
        if sec:
            servers.append(sec)
            
        success, errors = apply_dns_settings(adapter, servers)
        
        if success:
            self.status_text.configure(text=f"DNS başarıyla uygulandı: {dns_config['name']}", fg=COLOR_GREEN)
            self.update_current_dns_display()
            messagebox.showinfo("Başarılı", f"DNS ayarları başarıyla güncellendi!\nSeçilen: {dns_config['name']}\nIPler: {', '.join(servers)}")
        else:
            self.status_text.configure(text="DNS uygulanırken hata oluştu!", fg=COLOR_RED)
            err_msg = "\n".join(errors)
            messagebox.showerror("Hata", f"DNS ayarları uygulanamadı:\n{err_msg}")

    def reset_dns(self):
        adapter = self.current_adapter.get()
        if not adapter:
            messagebox.showerror("Hata", "Lütfen bir ağ adaptörü seçin!")
            return
            
        self.status_text.configure(text="DNS ayarları otomatik (DHCP) olarak sıfırlanıyor...", fg=COLOR_CYAN)
        self.root.update_idletasks()
        
        success, errors = apply_dns_settings(adapter, [])
        
        if success:
            self.status_text.configure(text="DNS ayarları sıfırlandı (Otomatik DHCP).", fg=COLOR_GREEN)
            self.update_current_dns_display()
            messagebox.showinfo("Başarılı", "DNS ayarları başarıyla sıfırlandı. Artık DNS adresleri internet servis sağlayıcınız tarafından otomatik alınacak.")
        else:
            self.status_text.configure(text="Sıfırlama sırasında hata oluştu!", fg=COLOR_RED)
            err_msg = "\n".join(errors)
            messagebox.showerror("Hata", f"DNS sıfırlanamadı:\n{err_msg}")


if __name__ == "__main__":
    # 1. Enforce Admin Access
    if not is_admin():
        run_as_admin()
    else:
        # 2. Start Application
        root = tk.Tk()
        
        # Apply style overrides for combobox to match theme
        style = ttk.Style()
        style.theme_use('vista' if 'vista' in ttk.Style().theme_names() else 'default')
        style.configure("TCombobox", 
                        fieldbackground=COLOR_CARD, 
                        background=COLOR_CARD, 
                        foreground=COLOR_TEXT_PRIMARY,
                        arrowcolor=COLOR_TEXT_PRIMARY,
                        bd=0)
        style.map("TCombobox", 
                  fieldbackground=[("readonly", COLOR_CARD)],
                  foreground=[("readonly", COLOR_TEXT_PRIMARY)])
        
        # Configure scrollbar style
        style.configure("TScrollbar",
                        background=COLOR_CARD,
                        troughcolor=COLOR_BG,
                        bordercolor=COLOR_BORDER,
                        arrowcolor=COLOR_TEXT_MUTED)
                        
        app = App(root)
        root.mainloop()
