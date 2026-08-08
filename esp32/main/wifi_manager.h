#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "esp_wifi_types.h"

#define FELICITY_WIFI_MAX_NETWORKS 24
#define FELICITY_WIFI_SSID_MAX 32
#define FELICITY_WIFI_PASSWORD_MAX 64
#define FELICITY_WIFI_LOG_MAX_LINES 8
#define FELICITY_WIFI_LOG_LINE_MAX 48

typedef enum {
    WIFI_MANAGER_IDLE = 0,
    WIFI_MANAGER_SCANNING,
    WIFI_MANAGER_SCAN_READY,
    WIFI_MANAGER_CONNECTING,
    WIFI_MANAGER_CONNECTED,
    WIFI_MANAGER_FAILED,
} wifi_manager_state_t;

typedef struct {
    char ssid[FELICITY_WIFI_SSID_MAX + 1];
    int8_t rssi;
    wifi_auth_mode_t authmode;
    uint8_t primary_channel;
    uint8_t bssid[6];
} wifi_network_t;

typedef struct {
    wifi_manager_state_t state;
    bool connected;
    char ssid[FELICITY_WIFI_SSID_MAX + 1];
    char ip[16];
    char gateway[16];
    char setup_ap[FELICITY_WIFI_SSID_MAX + 1];
    bool setup_ap_active;
    int8_t rssi;
    uint8_t channel;
    float tx_power_dbm;
} wifi_diagnostics_t;

void wifi_manager_init(void);
wifi_manager_state_t wifi_manager_state(void);
bool wifi_manager_enable_setup_ap(void);
void wifi_manager_disable_setup_ap(void);
bool wifi_manager_setup_ap_active(void);

bool wifi_manager_load_credentials(char *ssid, size_t ssid_size,
                                   char *password, size_t password_size);
bool wifi_manager_take_staged_credentials(char *ssid, size_t ssid_size,
                                          char *password, size_t password_size);
void wifi_manager_stage_credentials_and_restart(const char *ssid,
                                                const char *password);
void wifi_manager_request_setup_and_restart(void);
bool wifi_manager_take_setup_request(void);
bool wifi_manager_factory_reset(void);
void wifi_manager_start_scan(void);
size_t wifi_manager_network_count(void);
const wifi_network_t *wifi_manager_network(size_t index);

void wifi_manager_connect(const char *ssid, const char *password, bool save_on_success);
void wifi_manager_connect_network(const wifi_network_t *network, const char *password,
                                  bool save_on_success);
void wifi_manager_tick(void);
int wifi_manager_last_disconnect_reason(void);
bool wifi_manager_get_diagnostics(wifi_diagnostics_t *diagnostics);
size_t wifi_manager_log_snapshot(
    char lines[][FELICITY_WIFI_LOG_LINE_MAX], size_t max_lines,
    uint32_t *revision);
