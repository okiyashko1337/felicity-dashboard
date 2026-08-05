#include "setup_ui.h"

#include <ctype.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

#include "esp_idf_version.h"
#include "esp_system.h"
#include "nextion.h"
#include "wifi_manager.h"

enum {
    COLOR_BACKGROUND = 2307,
    COLOR_PANEL = 4386,
    COLOR_KEY = 6597,
    COLOR_ACCENT = 2016,
    COLOR_WARNING = 64495,
    COLOR_TEXT = 65535,
    COLOR_MUTED = 33840,
};

static void safe_label(const char *source, char *destination, size_t size)
{
    if (!size) return;
    size_t output = 0;
    for (size_t i = 0; source && source[i] && output + 1 < size; ++i) {
        unsigned char value = (unsigned char)source[i];
        destination[output++] = value < 32 || value > 126 || value == '"' || value == '\\'
                                    ? '?'
                                    : (char)value;
    }
    destination[output] = '\0';
}

static void clear_screen(void)
{
    nextion_command("page home");
    nextion_command("fill 0,0,480,272,%d", COLOR_BACKGROUND);
}

static void key(int x, int y, int width, int height, const char *label, int color)
{
    nextion_command("fill %d,%d,%d,%d,%d", x, y, width, height, color);
    nextion_text(x, y, width, height, 2, COLOR_TEXT, color, label);
}

static void touch_outline(int x, int y, int width, int height, int base_color,
                          bool pressed)
{
    int color = pressed ? COLOR_TEXT : base_color;
    nextion_command("draw %d,%d,%d,%d,%d", x, y, x + width - 1, y + height - 1,
                    color);
    nextion_command("draw %d,%d,%d,%d,%d", x + 1, y + 1, x + width - 2,
                    y + height - 2, color);
}

static const char *symbol_label(char value)
{
    if (value == '"') return "DQ";
    if (value == '\\') return "BS";
    if (value == '`') return "BT";
    static char label[2];
    label[0] = value;
    label[1] = '\0';
    return label;
}

void setup_ui_render_scanning(void)
{
    clear_screen();
    nextion_text(12, 8, 260, 28, 3, COLOR_TEXT, COLOR_BACKGROUND, "WI-FI SETUP");
    nextion_text(30, 104, 420, 36, 3, COLOR_ACCENT, COLOR_BACKGROUND, "SCANNING NETWORKS...");
}

void setup_ui_render_wizard_exit_top(bool visible)
{
    if (visible) key(370, 5, 100, 34, "EXIT", COLOR_WARNING);
}

void setup_ui_render_wizard_exit_bottom(bool visible)
{
    if (visible) key(352, 228, 120, 38, "EXIT", COLOR_WARNING);
}

void setup_ui_wizard_exit_touch_feedback(bool bottom, bool pressed)
{
    if (bottom) touch_outline(352, 228, 120, 38, COLOR_WARNING, pressed);
    else touch_outline(370, 5, 100, 34, COLOR_WARNING, pressed);
}

void setup_ui_render_factory_reset_result(bool success)
{
    clear_screen();
    nextion_text(20, 92, 440, 38, 0,
                 success ? COLOR_ACCENT : COLOR_WARNING, COLOR_BACKGROUND,
                 success ? "SETTINGS ERASED" : "RESET FAILED");
    nextion_text(20, 142, 440, 28, 0, COLOR_MUTED, COLOR_BACKGROUND,
                 success ? "RESTARTING..." : "PRESS BACK AND RETRY");
}

void setup_ui_render_wizard_exit_status(void)
{
    clear_screen();
    nextion_text(20, 104, 440, 38, 0, COLOR_ACCENT, COLOR_BACKGROUND,
                 "RESTORING SAVED WI-FI");
    nextion_text(20, 150, 440, 26, 0, COLOR_MUTED, COLOR_BACKGROUND,
                 "RESTARTING...");
}

void setup_ui_render_networks(size_t page, const char *message)
{
    clear_screen();
    nextion_text(12, 6, 220, 32, 3, COLOR_TEXT, COLOR_BACKGROUND, "SELECT WI-FI");
    key(370, 5, 100, 34, "RESCAN", COLOR_ACCENT);

    size_t count = wifi_manager_network_count();
    if (count == 0) {
        nextion_text(20, 92, 440, 34, 3, COLOR_WARNING, COLOR_BACKGROUND, "NO NETWORKS FOUND");
    }
    for (size_t row = 0; row < SETUP_WIFI_ROWS_PER_PAGE; ++row) {
        size_t index = page * SETUP_WIFI_ROWS_PER_PAGE + row;
        if (index >= count) break;
        const wifi_network_t *network = wifi_manager_network(index);
        int y = 48 + (int)row * 36;
        char ssid[27];
        char detail[20];
        safe_label(network->ssid, ssid, sizeof(ssid));
        snprintf(detail, sizeof(detail), "%s  %d dBm",
                 network->authmode == WIFI_AUTH_OPEN ? "OPEN" : "LOCK", network->rssi);
        nextion_command("fill 8,%d,464,33,%d", y, COLOR_PANEL);
        nextion_text(16, y + 2, 278, 29, 2, COLOR_TEXT, COLOR_PANEL, ssid);
        nextion_text(300, y + 2, 162, 29, 2, COLOR_MUTED, COLOR_PANEL, detail);
    }

    char pages[32];
    size_t page_count = count ? (count + SETUP_WIFI_ROWS_PER_PAGE - 1) / SETUP_WIFI_ROWS_PER_PAGE : 1;
    snprintf(pages, sizeof(pages), "%u / %u", (unsigned)(page + 1), (unsigned)page_count);
    if (page > 0) key(8, 232, 96, 34, "PREV", COLOR_KEY);
    nextion_text(190, 234, 100, 30, 2, COLOR_MUTED, COLOR_BACKGROUND, pages);
    if ((page + 1) * SETUP_WIFI_ROWS_PER_PAGE < count) key(376, 232, 96, 34, "NEXT", COLOR_KEY);
    if (message && message[0]) nextion_text(110, 234, 260, 28, 2, COLOR_WARNING, COLOR_BACKGROUND, message);
}

void setup_ui_render_keyboard(const char *ssid, const char *password,
                              bool symbols, bool uppercase, bool show_password,
                              const char *message)
{
    clear_screen();
    char safe_ssid[24];
    safe_label(ssid, safe_ssid, sizeof(safe_ssid));
    nextion_text(6, 2, 182, 22, 2, COLOR_MUTED, COLOR_BACKGROUND, safe_ssid);
    setup_ui_render_password(password, show_password, message);

    static const char *alpha_labels[] = {"1234567890", "qwertyuiop", "asdfghjkl"};
    static const char symbol_values[][11] = {"!@#$%^&*()", "-_=+[]{}<>", ";:'\",.?/\\|"};
    for (size_t row = 0; row < 3; ++row) {
        const char *values = symbols ? symbol_values[row] : alpha_labels[row];
        int start = row == 2 ? 28 : 5;
        for (size_t column = 0; column < strlen(values); ++column) {
            char label[2] = {values[column], '\0'};
            const char *shown = symbols ? symbol_label(values[column]) : label;
            if (!symbols && uppercase && row > 0) label[0] = (char)toupper((unsigned char)label[0]);
            key(start + (int)column * 47, 52 + (int)row * 42, 44, 39, shown, COLOR_KEY);
        }
    }
    key(5, 178, 57, 40, symbols ? "ABC" : (uppercase ? "abc" : "ABC"), COLOR_ACCENT);
    const char *last = symbols ? "`~" : "zxcvbnm";
    int start = symbols ? 145 : 70;
    int width = symbols ? 47 : 44;
    for (size_t i = 0; i < strlen(last); ++i) {
        char label[2] = {last[i], '\0'};
        if (!symbols && uppercase) label[0] = (char)toupper((unsigned char)label[0]);
        key(start + (int)i * width, 178, width - 3, 40,
            symbols ? symbol_label(last[i]) : label, COLOR_KEY);
    }
    key(385, 178, 87, 40, "BACK", COLOR_WARNING);
    key(5, 222, 75, 45, "CANCEL", COLOR_KEY);
    key(83, 222, 63, 45, symbols ? "ABC" : "#+=", COLOR_ACCENT);
    key(149, 222, 114, 45, "SPACE", COLOR_KEY);
    key(266, 222, 81, 45, show_password ? "HIDE" : "SHOW", COLOR_KEY);
    key(350, 222, 122, 45, "CONNECT", COLOR_ACCENT);
}

void setup_ui_render_password(const char *password, bool show_password,
                              const char *message)
{
    char display[34];
    size_t length = password ? strlen(password) : 0;
    if (show_password) {
        safe_label(length > 30 ? password + length - 30 : password, display, sizeof(display));
    } else {
        size_t visible = length > 30 ? 30 : length;
        memset(display, '*', visible);
        display[visible] = '\0';
    }
    nextion_command("fill 190,2,282,42,%d", COLOR_PANEL);
    nextion_text(198, 4, 266, 38, 2, COLOR_TEXT, COLOR_PANEL, display);
    nextion_command("fill 5,25,180,22,%d", COLOR_BACKGROUND);
    if (message && message[0]) {
        nextion_text(6, 26, 178, 20, 2, COLOR_WARNING, COLOR_BACKGROUND, message);
    }
}

void setup_ui_render_api_keyboard(const char *url, bool symbols,
                                  bool uppercase, const char *message)
{
    setup_ui_render_keyboard("HA ADDRESS", url, symbols, uppercase, true,
                             message);
    key(266, 222, 81, 45, "CLEAR", COLOR_KEY);
    key(350, 222, 122, 45, "SAVE", COLOR_ACCENT);
}

void setup_ui_render_connecting(const char *ssid)
{
    clear_screen();
    char safe_ssid[34];
    safe_label(ssid, safe_ssid, sizeof(safe_ssid));
    nextion_text(20, 78, 440, 38, 3, COLOR_ACCENT, COLOR_BACKGROUND, "CONNECTING...");
    nextion_text(20, 126, 440, 32, 2, COLOR_TEXT, COLOR_BACKGROUND, safe_ssid);
    nextion_text(20, 175, 440, 24, 2, COLOR_MUTED, COLOR_BACKGROUND, "WAITING FOR LOCAL IP");
}

void setup_ui_render_connection_log(
    const char *ssid,
    const char lines[][FELICITY_WIFI_LOG_LINE_MAX], size_t line_count,
    bool failed, bool connected)
{
    clear_screen();
    char safe_ssid[34];
    safe_label(ssid, safe_ssid, sizeof(safe_ssid));
    nextion_text(8, 4, 250, 26, 3, COLOR_TEXT, COLOR_BACKGROUND, "WI-FI LOG");
    nextion_text(260, 5, 212, 24, 2, COLOR_MUTED, COLOR_BACKGROUND, safe_ssid);
    nextion_command("fill 8,36,464,184,%d", COLOR_PANEL);
    for (size_t i = 0; i < line_count && i < FELICITY_WIFI_LOG_MAX_LINES; ++i) {
        char safe_line[FELICITY_WIFI_LOG_LINE_MAX];
        safe_label(lines[i], safe_line, sizeof(safe_line));
        int color = strstr(safe_line, "ERROR") || strstr(safe_line, "FAILED")
                        ? COLOR_WARNING
                        : (strstr(safe_line, "CONNECTED") ? COLOR_ACCENT : COLOR_TEXT);
        nextion_text(16, 40 + (int)i * 22, 448, 21, 2, color, COLOR_PANEL,
                     safe_line);
    }
    if (failed) {
        key(8, 228, 112, 38, "BACK", COLOR_WARNING);
        nextion_text(132, 232, 340, 30, 2, COLOR_WARNING, COLOR_BACKGROUND,
                     "CONNECTION FAILED");
    } else if (connected) {
        nextion_text(8, 232, 464, 30, 2, COLOR_ACCENT, COLOR_BACKGROUND,
                     "CONNECTED - OPENING DASHBOARD");
    } else {
        nextion_text(8, 232, 464, 30, 2, COLOR_MUTED, COLOR_BACKGROUND,
                     "PLEASE WAIT...");
    }
}

void setup_ui_connection_log_touch_feedback(uint16_t x, uint16_t y,
                                            bool pressed)
{
    if (x < 128 && y >= 224) {
        touch_outline(8, 228, 112, 38, COLOR_WARNING, pressed);
    }
}

void setup_ui_network_touch_feedback(uint16_t x, uint16_t y, size_t page,
                                     size_t network_count, bool pressed)
{
    setup_action_t action = setup_input_scan_hit(x, y, page, network_count);
    switch (action.type) {
        case SETUP_ACTION_RESCAN:
            touch_outline(370, 5, 100, 34, COLOR_ACCENT, pressed);
            break;
        case SETUP_ACTION_NETWORK: {
            size_t row = action.network_index % SETUP_WIFI_ROWS_PER_PAGE;
            touch_outline(8, 48 + (int)row * 36, 464, 33, COLOR_PANEL, pressed);
            break;
        }
        case SETUP_ACTION_PREVIOUS:
            touch_outline(8, 232, 96, 34, COLOR_KEY, pressed);
            break;
        case SETUP_ACTION_NEXT:
            touch_outline(376, 232, 96, 34, COLOR_KEY, pressed);
            break;
        default:
            break;
    }
}

void setup_ui_keyboard_touch_feedback(uint16_t x, uint16_t y, bool symbols,
                                      bool uppercase, bool pressed)
{
    setup_action_t action = setup_input_keyboard_hit(x, y, symbols, uppercase);
    if (action.type == SETUP_ACTION_NONE) return;

    if (y >= 52 && y < 176) {
        int row = (y - 52) / 42;
        int start = row == 2 ? 28 : 5;
        int column = ((int)x - start) / 47;
        touch_outline(start + column * 47, 52 + row * 42, 44, 39, COLOR_KEY, pressed);
        return;
    }
    if (y >= 178 && y < 218) {
        if (x < 62) {
            touch_outline(5, 178, 57, 40, COLOR_ACCENT, pressed);
        } else if (x >= 385) {
            touch_outline(385, 178, 87, 40, COLOR_WARNING, pressed);
        } else {
            int step = symbols ? 47 : 44;
            int start = symbols ? 145 : 70;
            int column = ((int)x - start) / step;
            touch_outline(start + column * step, 178, step - 3, 40, COLOR_KEY, pressed);
        }
        return;
    }
    if (x < 80) touch_outline(5, 222, 75, 45, COLOR_KEY, pressed);
    else if (x < 146) touch_outline(83, 222, 63, 45, COLOR_ACCENT, pressed);
    else if (x < 263) touch_outline(149, 222, 114, 45, COLOR_KEY, pressed);
    else if (x < 347) touch_outline(266, 222, 81, 45, COLOR_KEY, pressed);
    else touch_outline(350, 222, 122, 45, COLOR_ACCENT, pressed);
}

static const char *manager_state_label(wifi_manager_state_t state)
{
    switch (state) {
        case WIFI_MANAGER_SCANNING: return "SCANNING";
        case WIFI_MANAGER_SCAN_READY: return "READY";
        case WIFI_MANAGER_CONNECTING: return "CONNECTING";
        case WIFI_MANAGER_CONNECTED: return "CONNECTED";
        case WIFI_MANAGER_FAILED: return "FAILED";
        default: return "IDLE";
    }
}

static void scroll_arrow(int x, int y, bool down)
{
    nextion_command("draw %d,%d,%d,%d,%d", x, y, x + 37, y + 37,
                    COLOR_MUTED);
    int middle = x + 18;
    int tip = down ? y + 25 : y + 11;
    int wings = down ? y + 12 : y + 24;
    nextion_command("line %d,%d,%d,%d,%d", x + 8, wings, middle, tip,
                    COLOR_TEXT);
    nextion_command("line %d,%d,%d,%d,%d", middle, tip, x + 29, wings,
                    COLOR_TEXT);
}

static void setup_chrome(unsigned page)
{
    static const char *labels[] = {"NETWORK", "TIME", "RESET"};
    key(8, 5, 72, 32, "BACK", COLOR_KEY);
    nextion_text(90, 5, 185, 30, 2, COLOR_TEXT, COLOR_BACKGROUND,
                 "LOCAL SETUP");

    char counter[8];
    snprintf(counter, sizeof(counter), "%u/3", page + 1);
    scroll_arrow(366, 3, false);
    nextion_text(405, 5, 34, 30, 2, COLOR_MUTED, COLOR_BACKGROUND, counter);
    scroll_arrow(438, 3, true);

    nextion_command("fill 8,45,104,219,%d", COLOR_PANEL);
    nextion_text(15, 51, 90, 18, 2, COLOR_MUTED, COLOR_PANEL, "SETTINGS");
    for (unsigned index = 0; index < 3; ++index) {
        int y = 78 + (int)index * 48;
        int color = index == page ? COLOR_ACCENT : COLOR_TEXT;
        nextion_text(14, y, 92, 34, 2, color, COLOR_PANEL, labels[index]);
        if (index == page) {
            nextion_command("draw 10,%d,108,%d,%d", y - 2, y + 35,
                            COLOR_ACCENT);
        }
    }
}

void setup_ui_render_time_value(void)
{
    char value[40] = "--.--.----  --:--:--";
    time_t now = time(NULL);
    struct tm local = {0};
    if (now > 1700000000 && localtime_r(&now, &local)) {
        strftime(value, sizeof(value), "%d.%m.%Y  %H:%M:%S", &local);
    }
    nextion_command("fill 130,72,330,34,%d", COLOR_PANEL);
    nextion_text(130, 72, 330, 34, 0, COLOR_TEXT, COLOR_PANEL, value);
}

void setup_ui_render_local_settings(const wifi_diagnostics_t *wifi,
                                    const char *ha_host, bool ha_live,
                                    const char *status, unsigned page,
                                    const device_time_settings_t *time_settings,
                                    const char *ha_app_version,
                                    const char *monitor_version,
                                    uint32_t uptime_seconds)
{
    clear_screen();
    if (page < 3) setup_chrome(page);

    if (page == 1) {
        nextion_command("fill 120,45,352,160,%d", COLOR_PANEL);
        nextion_text(130, 49, 330, 20, 0, COLOR_MUTED, COLOR_PANEL,
                     "TIME SETTINGS");
        char value[40] = "--.--.----  --:--:--";
        time_t now = time(NULL);
        struct tm local = {0};
        if (now > 1700000000 && localtime_r(&now, &local)) {
            strftime(value, sizeof(value), "%d.%m.%Y  %H:%M:%S", &local);
        }
        nextion_text(130, 72, 330, 34, 0, COLOR_TEXT, COLOR_PANEL, value);
        nextion_text(130, 110, 330, 22, 0, COLOR_TEXT, COLOR_PANEL,
                     "SOURCE  HOME ASSISTANT");
        char line[64];
        int offset = time_settings ? time_settings->offset_minutes : 60;
        int absolute = offset < 0 ? -offset : offset;
        snprintf(line, sizeof(line), "BASE UTC%c%02d:%02d",
                 offset < 0 ? '-' : '+', absolute / 60, absolute % 60);
        nextion_text(130, 137, 330, 22, 0, COLOR_TEXT, COLOR_PANEL, line);
        nextion_text(130, 164, 330, 22, 0, COLOR_TEXT, COLOR_PANEL,
                     time_settings && time_settings->european_dst
                         ? "EUROPE DST  AUTO"
                         : "DST  OFF");
        key(120, 218, 104, 46, "-30 MIN", COLOR_KEY);
        key(230, 218, 104, 46, "+30 MIN", COLOR_KEY);
        key(340, 218, 132, 46,
            time_settings && time_settings->european_dst ? "DST ON" : "DST OFF",
            COLOR_ACCENT);
        return;
    }

    if (page == 2) {
        nextion_command("fill 120,45,352,155,%d", COLOR_PANEL);
        nextion_text(132, 50, 328, 22, 2, COLOR_MUTED, COLOR_PANEL,
                     "ABOUT");
        char line[64];
        snprintf(line, sizeof(line), "MONITOR  %s",
                 monitor_version && monitor_version[0] ? monitor_version : "--");
        nextion_text(132, 76, 328, 22, 0, COLOR_TEXT, COLOR_PANEL, line);
        snprintf(line, sizeof(line), "HA APP   %s",
                 ha_app_version && ha_app_version[0] ? ha_app_version : "--");
        nextion_text(132, 101, 328, 22, 0, COLOR_TEXT, COLOR_PANEL, line);
        snprintf(line, sizeof(line), "ESP-IDF  %s", esp_get_idf_version());
        nextion_text(132, 126, 328, 22, 0, COLOR_TEXT, COLOR_PANEL, line);
        uint32_t hours = uptime_seconds / 3600;
        uint32_t minutes = (uptime_seconds / 60) % 60;
        snprintf(line, sizeof(line), "UPTIME   %uh %02um",
                 (unsigned)hours, (unsigned)minutes);
        nextion_text(132, 151, 328, 22, 0, COLOR_TEXT, COLOR_PANEL, line);
        nextion_text(132, 176, 328, 18, 2, COLOR_WARNING, COLOR_PANEL,
                     "RESET ERASES ALL SETTINGS");
        key(174, 211, 244, 53, "RESET ALL", COLOR_WARNING);
        return;
    }

    if (page == 3) {
        key(8, 5, 72, 32, "BACK", COLOR_KEY);
        nextion_text(90, 5, 300, 30, 2, COLOR_TEXT, COLOR_BACKGROUND,
                     "CONFIRM RESET");
        nextion_command("fill 20,54,440,126,%d", COLOR_PANEL);
        nextion_text(32, 62, 416, 30, 0, COLOR_WARNING, COLOR_PANEL,
                     "ERASE ALL SETTINGS?");
        nextion_text(32, 102, 416, 24, 0, COLOR_TEXT, COLOR_PANEL,
                     "THIS CANNOT BE UNDONE");
        nextion_text(32, 133, 416, 24, 0, COLOR_MUTED, COLOR_PANEL,
                     "SETUP WILL START AFTER REBOOT");
        key(24, 202, 192, 56, "CANCEL", COLOR_KEY);
        key(264, 202, 192, 56, "YES, ERASE", COLOR_WARNING);
        return;
    }

    nextion_command("fill 120,45,352,78,%d", COLOR_PANEL);
    char line[96];
    snprintf(line, sizeof(line), "WI-FI  %s",
             wifi ? manager_state_label(wifi->state) : "--");
    nextion_text(130, 48, 220, 19, 0, COLOR_MUTED, COLOR_PANEL, line);
    char safe_value[48];
    safe_label(wifi ? wifi->ssid : "--", safe_value, sizeof(safe_value));
    snprintf(line, sizeof(line), "SSID  %s", safe_value);
    nextion_text(130, 67, 220, 18, 0, COLOR_TEXT, COLOR_PANEL, line);
    snprintf(line, sizeof(line), "IP  %s", wifi ? wifi->ip : "--");
    nextion_text(130, 86, 220, 18, 0, COLOR_TEXT, COLOR_PANEL, line);
    snprintf(line, sizeof(line), "%d dBm  CH%u  TX%.1f",
             wifi ? wifi->rssi : 0, wifi ? wifi->channel : 0,
             wifi ? wifi->tx_power_dbm : 0.0f);
    nextion_text(130, 104, 220, 18, 0, COLOR_MUTED, COLOR_PANEL, line);
    key(360, 57, 104, 54, "WI-FI", COLOR_ACCENT);

    nextion_command("fill 120,131,352,70,%d", COLOR_PANEL);
    nextion_text(130, 136, 210, 20, 2, COLOR_MUTED, COLOR_PANEL,
                 "HOME ASSISTANT");
    safe_label(ha_host, safe_value, sizeof(safe_value));
    nextion_text(130, 158, 220, 28, 2, COLOR_TEXT, COLOR_PANEL, safe_value);
    nextion_text(130, 181, 220, 17, 2,
                 ha_live ? COLOR_ACCENT : COLOR_WARNING, COLOR_PANEL,
                 ha_live ? "DATA AVAILABLE" : "DATA NOT AVAILABLE");
    key(360, 139, 104, 54, "EDIT HA", COLOR_ACCENT);

    nextion_command("fill 120,209,232,55,%d", COLOR_PANEL);
    nextion_text(130, 214, 210, 18, 2, COLOR_MUTED, COLOR_PANEL,
                 "CURRENT STATUS");
    safe_label(status && status[0] ? status : "READY", safe_value,
               sizeof(safe_value));
    nextion_text(130, 235, 210, 24, 2,
                 ha_live ? COLOR_ACCENT : COLOR_WARNING, COLOR_PANEL,
                 safe_value);
    key(360, 209, 104, 55, "RETRY", COLOR_KEY);
}

local_setup_action_t setup_ui_local_settings_hit(uint16_t x, uint16_t y,
                                                  unsigned page)
{
    if (x >= 8 && x < 80 && y >= 5 && y < 39) {
        return page == 3 ? LOCAL_SETUP_ACTION_RESET_CANCEL
                         : LOCAL_SETUP_ACTION_BACK;
    }
    if (page < 3 && x >= 8 && x < 112) {
        if (y >= 72 && y < 120) return LOCAL_SETUP_ACTION_NAV_NETWORK;
        if (y >= 120 && y < 168) return LOCAL_SETUP_ACTION_NAV_TIME;
        if (y >= 168 && y < 216) return LOCAL_SETUP_ACTION_NAV_RESET;
    }
    if (page < 3 && y < 43) {
        if (x >= 358 && x < 404) return LOCAL_SETUP_ACTION_UP;
        if (x >= 432) return LOCAL_SETUP_ACTION_DOWN;
    }
    if (page == 1) {
        if (y >= 212 && x >= 116 && x < 228) return LOCAL_SETUP_ACTION_TIME_MINUS;
        if (y >= 212 && x >= 228 && x < 338) return LOCAL_SETUP_ACTION_TIME_PLUS;
        if (y >= 212 && x >= 338) return LOCAL_SETUP_ACTION_TIME_DST;
        return LOCAL_SETUP_ACTION_NONE;
    }
    if (page == 2) {
        if (y >= 205 && x >= 166 && x < 426) return LOCAL_SETUP_ACTION_RESET;
        return LOCAL_SETUP_ACTION_NONE;
    }
    if (page == 3) {
        if (y >= 195 && x < 232) return LOCAL_SETUP_ACTION_RESET_CANCEL;
        if (y >= 195 && x >= 248) return LOCAL_SETUP_ACTION_RESET_CONFIRM;
        return LOCAL_SETUP_ACTION_NONE;
    }
    if (x >= 354 && x < 472 && y >= 52 && y < 123) return LOCAL_SETUP_ACTION_WIFI;
    if (x >= 354 && x < 472 && y >= 131 && y < 201) return LOCAL_SETUP_ACTION_HA;
    if (x >= 354 && x < 472 && y >= 205 && y < 272) return LOCAL_SETUP_ACTION_RETRY;
    return LOCAL_SETUP_ACTION_NONE;
}

void setup_ui_local_settings_touch_feedback(uint16_t x, uint16_t y,
                                            bool pressed, unsigned page)
{
    switch (setup_ui_local_settings_hit(x, y, page)) {
        case LOCAL_SETUP_ACTION_BACK:
            touch_outline(8, 5, 72, 32, COLOR_KEY, pressed);
            break;
        case LOCAL_SETUP_ACTION_WIFI:
            touch_outline(360, 57, 104, 54, COLOR_ACCENT, pressed);
            break;
        case LOCAL_SETUP_ACTION_HA:
            touch_outline(360, 139, 104, 54, COLOR_ACCENT, pressed);
            break;
        case LOCAL_SETUP_ACTION_RETRY:
            touch_outline(360, 209, 104, 55, COLOR_KEY, pressed);
            break;
        case LOCAL_SETUP_ACTION_DOWN:
            touch_outline(438, 3, 38, 38, COLOR_MUTED, pressed);
            break;
        case LOCAL_SETUP_ACTION_UP:
            touch_outline(366, 3, 38, 38, COLOR_MUTED, pressed);
            break;
        case LOCAL_SETUP_ACTION_NAV_NETWORK:
            touch_outline(10, 76, 99, 38, COLOR_ACCENT, pressed);
            break;
        case LOCAL_SETUP_ACTION_NAV_TIME:
            touch_outline(10, 124, 99, 38, COLOR_ACCENT, pressed);
            break;
        case LOCAL_SETUP_ACTION_NAV_RESET:
            touch_outline(10, 172, 99, 38, COLOR_ACCENT, pressed);
            break;
        case LOCAL_SETUP_ACTION_TIME_MINUS:
            touch_outline(120, 218, 104, 46, COLOR_KEY, pressed);
            break;
        case LOCAL_SETUP_ACTION_TIME_PLUS:
            touch_outline(230, 218, 104, 46, COLOR_KEY, pressed);
            break;
        case LOCAL_SETUP_ACTION_TIME_DST:
            touch_outline(340, 218, 132, 46, COLOR_ACCENT, pressed);
            break;
        case LOCAL_SETUP_ACTION_RESET:
            touch_outline(174, 211, 244, 53, COLOR_WARNING, pressed);
            break;
        case LOCAL_SETUP_ACTION_RESET_CANCEL:
            touch_outline(24, 202, 192, 56, COLOR_KEY, pressed);
            break;
        case LOCAL_SETUP_ACTION_RESET_CONFIRM:
            touch_outline(264, 202, 192, 56, COLOR_WARNING, pressed);
            break;
        default:
            break;
    }
}
