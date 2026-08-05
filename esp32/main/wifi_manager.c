#include "wifi_manager.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>

#include "esp_event.h"
#include "esp_attr.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "nvs.h"

static const char *TAG = "wifi_manager";
static const char *NVS_NAMESPACE = "felicity_wifi";
static const char *NVS_SSID = "ssid";
static const char *NVS_PASSWORD = "password";
static const int64_t CONNECT_TIMEOUT_US = 30000000;
/* ESP32-C3 Super Mini V1.601 has unreliable 2.4 GHz transmission at the
 * 20 dBm ceiling: scans still work, but authentication frames and SoftAP
 * beacons can disappear over the air. esp_wifi uses quarter-dBm units. */
static const int8_t WIFI_TX_POWER_QDBM = 34; /* 8.5 dBm */
static const char *SETUP_AP_PREFIX = "Felicity-Setup";

static volatile wifi_manager_state_t state = WIFI_MANAGER_IDLE;
static wifi_network_t networks[FELICITY_WIFI_MAX_NETWORKS];
static size_t network_count;
static int disconnect_reason;
static int64_t connect_started_at;
static bool save_credentials_on_success;
static bool was_connected;
static char pending_ssid[FELICITY_WIFI_SSID_MAX + 1];
static char pending_password[FELICITY_WIFI_PASSWORD_MAX];
static char setup_ap_ssid[FELICITY_WIFI_SSID_MAX + 1];
static esp_netif_t *station_netif;
static char connection_log[FELICITY_WIFI_LOG_MAX_LINES][FELICITY_WIFI_LOG_LINE_MAX];
static size_t connection_log_count;
static uint32_t connection_log_revision;
static portMUX_TYPE connection_log_lock = portMUX_INITIALIZER_UNLOCKED;

#define STAGED_CREDENTIALS_MAGIC 0x46454c57U
#define FORCE_SETUP_MAGIC 0x46454c53U

typedef struct {
    uint32_t magic;
    uint32_t checksum;
    char ssid[FELICITY_WIFI_SSID_MAX + 1];
    char password[FELICITY_WIFI_PASSWORD_MAX];
} staged_credentials_t;

static RTC_NOINIT_ATTR staged_credentials_t staged_credentials;
static RTC_NOINIT_ATTR uint32_t force_setup_request;

static void connection_log_reset(void)
{
    taskENTER_CRITICAL(&connection_log_lock);
    memset(connection_log, 0, sizeof(connection_log));
    connection_log_count = 0;
    ++connection_log_revision;
    taskEXIT_CRITICAL(&connection_log_lock);
}

static void connection_log_append(const char *format, ...)
{
    char line[FELICITY_WIFI_LOG_LINE_MAX];
    va_list arguments;
    va_start(arguments, format);
    vsnprintf(line, sizeof(line), format, arguments);
    va_end(arguments);

    taskENTER_CRITICAL(&connection_log_lock);
    if (connection_log_count == FELICITY_WIFI_LOG_MAX_LINES) {
        memmove(connection_log, connection_log + 1,
                sizeof(connection_log[0]) * (FELICITY_WIFI_LOG_MAX_LINES - 1));
        --connection_log_count;
    }
    snprintf(connection_log[connection_log_count],
             sizeof(connection_log[connection_log_count]), "%s", line);
    ++connection_log_count;
    ++connection_log_revision;
    taskEXIT_CRITICAL(&connection_log_lock);
}

static const char *disconnect_reason_name(int reason)
{
    switch (reason) {
        case WIFI_REASON_AUTH_EXPIRE: return "AUTH TIMEOUT";
        case WIFI_REASON_NO_AP_FOUND: return "AP NOT FOUND";
        case WIFI_REASON_AUTH_FAIL: return "AUTH FAILED";
        case WIFI_REASON_ASSOC_FAIL: return "ASSOC FAILED";
        case WIFI_REASON_HANDSHAKE_TIMEOUT: return "HANDSHAKE TIMEOUT";
        default: return "DISCONNECTED";
    }
}

static uint32_t credentials_checksum(const staged_credentials_t *credentials)
{
    uint32_t value = 2166136261U;
    const uint8_t *bytes = (const uint8_t *)credentials->ssid;
    size_t length = sizeof(credentials->ssid) + sizeof(credentials->password);
    for (size_t i = 0; i < length; ++i) {
        value ^= bytes[i];
        value *= 16777619U;
    }
    return value;
}

static const char *auth_mode_name(wifi_auth_mode_t mode)
{
    switch (mode) {
        case WIFI_AUTH_OPEN: return "OPEN";
        case WIFI_AUTH_WEP: return "WEP";
        case WIFI_AUTH_WPA_PSK: return "WPA-PSK";
        case WIFI_AUTH_WPA2_PSK: return "WPA2-PSK";
        case WIFI_AUTH_WPA_WPA2_PSK: return "WPA/WPA2-PSK";
        case WIFI_AUTH_WPA2_ENTERPRISE: return "WPA2-ENTERPRISE";
        case WIFI_AUTH_WPA3_PSK: return "WPA3-PSK";
        case WIFI_AUTH_WPA2_WPA3_PSK: return "WPA2/WPA3-PSK";
        default: return "OTHER";
    }
}

static int compare_networks(const void *left, const void *right)
{
    const wifi_network_t *a = left;
    const wifi_network_t *b = right;
    return (int)b->rssi - (int)a->rssi;
}

static void save_credentials(void)
{
    nvs_handle_t handle;
    esp_err_t result = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &handle);
    if (result != ESP_OK) {
        ESP_LOGE(TAG, "Cannot open NVS: %s", esp_err_to_name(result));
        return;
    }
    result = nvs_set_str(handle, NVS_SSID, pending_ssid);
    if (result == ESP_OK) result = nvs_set_str(handle, NVS_PASSWORD, pending_password);
    if (result == ESP_OK) result = nvs_commit(handle);
    if (result != ESP_OK) ESP_LOGE(TAG, "Cannot save credentials: %s", esp_err_to_name(result));
    nvs_close(handle);
}

static void collect_scan_results(void)
{
    uint16_t count = 0;
    if (esp_wifi_scan_get_ap_num(&count) != ESP_OK || count == 0) {
        network_count = 0;
        state = WIFI_MANAGER_SCAN_READY;
        return;
    }

    wifi_ap_record_t *records = calloc(count, sizeof(*records));
    if (!records) {
        network_count = 0;
        state = WIFI_MANAGER_SCAN_READY;
        return;
    }
    if (esp_wifi_scan_get_ap_records(&count, records) != ESP_OK) {
        free(records);
        network_count = 0;
        state = WIFI_MANAGER_SCAN_READY;
        return;
    }

    network_count = 0;
    for (uint16_t i = 0; i < count && network_count < FELICITY_WIFI_MAX_NETWORKS; ++i) {
        if (!records[i].ssid[0]) continue;
        size_t existing = network_count;
        for (size_t j = 0; j < network_count; ++j) {
            if (strncmp(networks[j].ssid, (const char *)records[i].ssid,
                        FELICITY_WIFI_SSID_MAX) == 0) {
                existing = j;
                break;
            }
        }
        if (existing < network_count) {
            if (records[i].rssi > networks[existing].rssi) {
                networks[existing].rssi = records[i].rssi;
                networks[existing].authmode = records[i].authmode;
                networks[existing].primary_channel = records[i].primary;
                memcpy(networks[existing].bssid, records[i].bssid,
                       sizeof(networks[existing].bssid));
            }
            continue;
        }
        wifi_network_t *network = &networks[network_count++];
        snprintf(network->ssid, sizeof(network->ssid), "%s", (const char *)records[i].ssid);
        network->rssi = records[i].rssi;
        network->authmode = records[i].authmode;
        network->primary_channel = records[i].primary;
        memcpy(network->bssid, records[i].bssid, sizeof(network->bssid));
    }
    free(records);
    qsort(networks, network_count, sizeof(networks[0]), compare_networks);
    state = WIFI_MANAGER_SCAN_READY;
    ESP_LOGI(TAG, "Scan complete: %u unique networks", (unsigned)network_count);
    for (size_t i = 0; i < network_count; ++i) {
        const wifi_network_t *network = &networks[i];
        ESP_LOGI(TAG, "AP[%u] ssid='%s' rssi=%d auth=%s(%d) channel=%u bssid=" MACSTR,
                 (unsigned)i, network->ssid, network->rssi,
                 auth_mode_name(network->authmode), network->authmode,
                 network->primary_channel, MAC2STR(network->bssid));
    }
}

static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg;
    if (base == WIFI_EVENT && id == WIFI_EVENT_SCAN_DONE) {
        if (state == WIFI_MANAGER_SCANNING) collect_scan_results();
        return;
    }
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        const wifi_event_sta_disconnected_t *event = data;
        disconnect_reason = event ? event->reason : 0;
        ESP_LOGW(TAG, "Disconnected from '%s': reason=%d, state=%d",
                 pending_ssid, disconnect_reason, state);
        connection_log_append("ERROR %d: %s", disconnect_reason,
                              disconnect_reason_name(disconnect_reason));
        if (was_connected) {
            state = WIFI_MANAGER_CONNECTING;
            connect_started_at = esp_timer_get_time();
            esp_wifi_connect();
        } else if (state == WIFI_MANAGER_CONNECTING) {
            state = WIFI_MANAGER_FAILED;
        }
        return;
    }
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_CONNECTED) {
        const wifi_event_sta_connected_t *event = data;
        connection_log_append("ASSOCIATED  CH %u", event ? event->channel : 0);
        connection_log_append("WAITING FOR DHCP...");
        return;
    }
    if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        const ip_event_got_ip_t *event = data;
        state = WIFI_MANAGER_CONNECTED;
        was_connected = true;
        disconnect_reason = 0;
        if (save_credentials_on_success) save_credentials();
        save_credentials_on_success = false;
        memset(pending_password, 0, sizeof(pending_password));
        if (event) {
            connection_log_append("CONNECTED  " IPSTR, IP2STR(&event->ip_info.ip));
        } else {
            connection_log_append("CONNECTED");
        }
    }
}

void wifi_manager_init(void)
{
    connection_log_reset();
    connection_log_append("BOOT: INITIALIZING WIFI");
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    station_netif = esp_netif_create_default_wifi_sta();
    ESP_ERROR_CHECK(station_netif ? ESP_OK : ESP_FAIL);
    ESP_ERROR_CHECK(esp_netif_create_default_wifi_ap() ? ESP_OK : ESP_FAIL);
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));

    uint8_t ap_mac[6] = {0};
    ESP_ERROR_CHECK(esp_read_mac(ap_mac, ESP_MAC_WIFI_SOFTAP));
    wifi_config_t ap_config = {0};
    snprintf((char *)ap_config.ap.ssid, sizeof(ap_config.ap.ssid),
             "%s-%02X%02X", SETUP_AP_PREFIX, ap_mac[4], ap_mac[5]);
    snprintf(setup_ap_ssid, sizeof(setup_ap_ssid), "%s",
             (char *)ap_config.ap.ssid);
    ap_config.ap.ssid_len = strlen((char *)ap_config.ap.ssid);
    ap_config.ap.channel = 1;
    ap_config.ap.authmode = WIFI_AUTH_OPEN;
    ap_config.ap.max_connection = 4;
    ap_config.ap.beacon_interval = 100;

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_APSTA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP, &ap_config));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_max_tx_power(WIFI_TX_POWER_QDBM));
    connection_log_append("SETUP AP: %s", ap_config.ap.ssid);
    connection_log_append("TX POWER: 8.5 dBm");
    ESP_LOGI(TAG, "Setup AP '%s', Wi-Fi TX power 8.5 dBm", ap_config.ap.ssid);
}

wifi_manager_state_t wifi_manager_state(void)
{
    return state;
}

bool wifi_manager_load_credentials(char *ssid, size_t ssid_size,
                                   char *password, size_t password_size)
{
    nvs_handle_t handle;
    if (!ssid || !password || ssid_size == 0 || password_size == 0) return false;
    ssid[0] = '\0';
    password[0] = '\0';
    if (nvs_open(NVS_NAMESPACE, NVS_READONLY, &handle) != ESP_OK) return false;
    size_t stored_ssid_size = ssid_size;
    size_t stored_password_size = password_size;
    esp_err_t ssid_result = nvs_get_str(handle, NVS_SSID, ssid, &stored_ssid_size);
    esp_err_t password_result = nvs_get_str(handle, NVS_PASSWORD, password, &stored_password_size);
    nvs_close(handle);
    return ssid_result == ESP_OK && password_result == ESP_OK && ssid[0] != '\0';
}

bool wifi_manager_take_staged_credentials(char *ssid, size_t ssid_size,
                                          char *password, size_t password_size)
{
    if (!ssid || !password || !ssid_size || !password_size) return false;
    bool valid = staged_credentials.magic == STAGED_CREDENTIALS_MAGIC &&
                 staged_credentials.checksum ==
                     credentials_checksum(&staged_credentials) &&
                 staged_credentials.ssid[0] != '\0';
    if (valid) {
        snprintf(ssid, ssid_size, "%s", staged_credentials.ssid);
        snprintf(password, password_size, "%s", staged_credentials.password);
    } else {
        ssid[0] = '\0';
        password[0] = '\0';
    }
    memset(&staged_credentials, 0, sizeof(staged_credentials));
    return valid;
}

void wifi_manager_stage_credentials_and_restart(const char *ssid,
                                                const char *password)
{
    memset(&staged_credentials, 0, sizeof(staged_credentials));
    snprintf(staged_credentials.ssid, sizeof(staged_credentials.ssid), "%s",
             ssid ? ssid : "");
    snprintf(staged_credentials.password, sizeof(staged_credentials.password),
             "%s", password ? password : "");
    staged_credentials.checksum = credentials_checksum(&staged_credentials);
    staged_credentials.magic = STAGED_CREDENTIALS_MAGIC;
    ESP_LOGI(TAG, "Credentials staged in RTC; restarting for clean STA connection");
    esp_restart();
}

void wifi_manager_request_setup_and_restart(void)
{
    force_setup_request = FORCE_SETUP_MAGIC;
    ESP_LOGI(TAG, "Restarting into interactive Wi-Fi setup");
    esp_restart();
}

bool wifi_manager_take_setup_request(void)
{
    bool requested = force_setup_request == FORCE_SETUP_MAGIC;
    force_setup_request = 0;
    return requested;
}

bool wifi_manager_factory_reset(void)
{
    memset(&staged_credentials, 0, sizeof(staged_credentials));
    force_setup_request = 0;
    nvs_handle_t handle;
    esp_err_t result = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &handle);
    if (result == ESP_ERR_NVS_NOT_FOUND) return true;
    if (result != ESP_OK) return false;
    result = nvs_erase_all(handle);
    if (result == ESP_OK) result = nvs_commit(handle);
    nvs_close(handle);
    return result == ESP_OK;
}

void wifi_manager_start_scan(void)
{
    if (state == WIFI_MANAGER_SCANNING) return;
    was_connected = false;
    network_count = 0;
    state = WIFI_MANAGER_SCANNING;
    esp_err_t result = esp_wifi_scan_start(NULL, false);
    if (result != ESP_OK) {
        ESP_LOGW(TAG, "Cannot start scan: %s", esp_err_to_name(result));
        state = WIFI_MANAGER_SCAN_READY;
    }
}

size_t wifi_manager_network_count(void)
{
    return network_count;
}

const wifi_network_t *wifi_manager_network(size_t index)
{
    return index < network_count ? &networks[index] : NULL;
}

static void connect_to_network(const wifi_network_t *network, const char *ssid,
                               const char *password, bool save_on_success)
{
    (void)network;
    const char *target_ssid = ssid ? ssid : "";
    const char *target_password = password ? password : "";

    wifi_config_t config = {0};
    snprintf((char *)config.sta.ssid, sizeof(config.sta.ssid), "%s",
             target_ssid);
    snprintf((char *)config.sta.password, sizeof(config.sta.password), "%s",
             target_password);

    snprintf(pending_ssid, sizeof(pending_ssid), "%s", target_ssid);
    snprintf(pending_password, sizeof(pending_password), "%s", target_password);
    ESP_LOGI(TAG, "Connecting to ssid='%s', password_length=%u",
             pending_ssid, (unsigned)strlen(pending_password));
    connection_log_append("SSID: %.32s", pending_ssid);
    connection_log_append("PASSWORD LENGTH: %u",
                          (unsigned)strlen(pending_password));
    connection_log_append("AUTHENTICATION REQUESTED");
    save_credentials_on_success = save_on_success;
    was_connected = false;
    disconnect_reason = 0;
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &config));
    state = WIFI_MANAGER_CONNECTING;
    connect_started_at = esp_timer_get_time();
    esp_err_t result = esp_wifi_connect();
    if (result != ESP_OK) {
        ESP_LOGW(TAG, "Cannot connect: %s", esp_err_to_name(result));
        connection_log_append("CONNECT ERROR: %s", esp_err_to_name(result));
        state = WIFI_MANAGER_FAILED;
    }
}

void wifi_manager_connect(const char *ssid, const char *password, bool save_on_success)
{
    connect_to_network(NULL, ssid, password, save_on_success);
}

void wifi_manager_connect_network(const wifi_network_t *network, const char *password,
                                  bool save_on_success)
{
    if (!network) return;
    connect_to_network(network, network->ssid, password, save_on_success);
}

void wifi_manager_tick(void)
{
    if (state == WIFI_MANAGER_CONNECTING &&
        esp_timer_get_time() - connect_started_at >= CONNECT_TIMEOUT_US) {
        esp_wifi_disconnect();
        state = WIFI_MANAGER_FAILED;
    }
}

int wifi_manager_last_disconnect_reason(void)
{
    return disconnect_reason;
}

bool wifi_manager_get_diagnostics(wifi_diagnostics_t *diagnostics)
{
    if (!diagnostics) return false;
    memset(diagnostics, 0, sizeof(*diagnostics));
    diagnostics->state = state;
    diagnostics->tx_power_dbm = WIFI_TX_POWER_QDBM / 4.0f;
    snprintf(diagnostics->setup_ap, sizeof(diagnostics->setup_ap), "%s",
             setup_ap_ssid);
    snprintf(diagnostics->ip, sizeof(diagnostics->ip), "--");
    snprintf(diagnostics->gateway, sizeof(diagnostics->gateway), "--");

    wifi_ap_record_t access_point = {0};
    if (esp_wifi_sta_get_ap_info(&access_point) == ESP_OK) {
        diagnostics->connected = true;
        snprintf(diagnostics->ssid, sizeof(diagnostics->ssid), "%s",
                 (const char *)access_point.ssid);
        diagnostics->rssi = access_point.rssi;
        diagnostics->channel = access_point.primary;
    } else {
        snprintf(diagnostics->ssid, sizeof(diagnostics->ssid), "%s",
                 pending_ssid[0] ? pending_ssid : "--");
    }

    esp_netif_ip_info_t info = {0};
    if (station_netif && esp_netif_get_ip_info(station_netif, &info) == ESP_OK &&
        info.ip.addr != 0) {
        snprintf(diagnostics->ip, sizeof(diagnostics->ip), IPSTR,
                 IP2STR(&info.ip));
        snprintf(diagnostics->gateway, sizeof(diagnostics->gateway), IPSTR,
                 IP2STR(&info.gw));
    }
    return diagnostics->connected;
}

size_t wifi_manager_log_snapshot(
    char lines[][FELICITY_WIFI_LOG_LINE_MAX], size_t max_lines,
    uint32_t *revision)
{
    taskENTER_CRITICAL(&connection_log_lock);
    size_t count = connection_log_count < max_lines ? connection_log_count : max_lines;
    size_t first = connection_log_count - count;
    for (size_t i = 0; i < count; ++i) {
        snprintf(lines[i], FELICITY_WIFI_LOG_LINE_MAX, "%s",
                 connection_log[first + i]);
    }
    if (revision) *revision = connection_log_revision;
    taskEXIT_CRITICAL(&connection_log_lock);
    return count;
}
