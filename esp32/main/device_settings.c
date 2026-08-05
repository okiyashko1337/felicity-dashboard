#include "device_settings.h"

#include <ctype.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <time.h>

#include "nvs.h"
#include "esp_log.h"
#include "mdns.h"
static const char *NVS_NAMESPACE = "felicity_cfg";
static const char *NVS_HA_HOST = "ha_host";
static const char *NVS_TZ_OFFSET = "tz_offset";
static const char *NVS_TZ_DST = "tz_dst";
static const char *DEFAULT_HA_HOST = "homeassistant.local";
static const char *TAG = "device_settings";
static bool mdns_started;

bool device_settings_ha_host_valid(const char *host)
{
    if (!host) return false;
    size_t length = strlen(host);
    if (length < 1 || length >= FELICITY_HA_HOST_MAX) return false;
    for (size_t i = 0; i < length; ++i) {
        unsigned char value = (unsigned char)host[i];
        if (!isalnum(value) && value != '.' && value != '-') return false;
    }
    return host[0] != '.' && host[length - 1] != '.';
}

bool device_settings_load_ha_host(char *output, size_t capacity)
{
    if (!output || capacity == 0) return false;
    snprintf(output, capacity, "%s", DEFAULT_HA_HOST);
    nvs_handle_t handle;
    if (nvs_open(NVS_NAMESPACE, NVS_READONLY, &handle) != ESP_OK) return false;
    size_t size = capacity;
    esp_err_t result = nvs_get_str(handle, NVS_HA_HOST, output, &size);
    nvs_close(handle);
    if (result != ESP_OK || !device_settings_ha_host_valid(output)) {
        snprintf(output, capacity, "%s", DEFAULT_HA_HOST);
        return false;
    }
    return true;
}

bool device_settings_save_ha_host(const char *host)
{
    if (!device_settings_ha_host_valid(host)) return false;
    nvs_handle_t handle;
    if (nvs_open(NVS_NAMESPACE, NVS_READWRITE, &handle) != ESP_OK) return false;
    esp_err_t result = nvs_set_str(handle, NVS_HA_HOST, host);
    if (result == ESP_OK) result = nvs_commit(handle);
    nvs_close(handle);
    return result == ESP_OK;
}

void device_settings_build_api_url(const char *host, char *output,
                                   size_t capacity)
{
    if (!output || capacity == 0) return;
    snprintf(output, capacity, "http://%s:8000", host ? host : DEFAULT_HA_HOST);
}

bool device_settings_prepare_api_url(const char *host, char *output,
                                     size_t capacity)
{
    if (!output || capacity == 0 || !device_settings_ha_host_valid(host)) {
        return false;
    }
    output[0] = '\0';
    size_t length = strlen(host);
    static const char suffix[] = ".local";
    if (length <= sizeof(suffix) - 1 ||
        strcmp(host + length - (sizeof(suffix) - 1), suffix) != 0) {
        device_settings_build_api_url(host, output, capacity);
        return true;
    }

    if (!mdns_started) {
        esp_err_t result = mdns_init();
        if (result != ESP_OK) {
            ESP_LOGW(TAG, "Cannot initialize mDNS: %s",
                     esp_err_to_name(result));
            return false;
        }
        mdns_started = true;
    }

    char label[FELICITY_HA_HOST_MAX];
    snprintf(label, sizeof(label), "%.*s",
             (int)(length - (sizeof(suffix) - 1)), host);
    esp_ip4_addr_t address = {0};
    esp_err_t result = mdns_query_a(label, 3000, &address);
    if (result != ESP_OK || address.addr == 0) {
        ESP_LOGW(TAG, "mDNS lookup for %s failed: %s", host,
                 esp_err_to_name(result));
        return false;
    }
    snprintf(output, capacity, "http://" IPSTR ":8000", IP2STR(&address));
    ESP_LOGI(TAG, "%s resolved to " IPSTR, host, IP2STR(&address));
    return true;
}

void device_settings_load_time(device_time_settings_t *settings)
{
    if (!settings) return;
    settings->offset_minutes = 60;
    settings->european_dst = true;
    nvs_handle_t handle;
    if (nvs_open(NVS_NAMESPACE, NVS_READONLY, &handle) != ESP_OK) return;
    int16_t offset = 60;
    uint8_t dst = 1;
    if (nvs_get_i16(handle, NVS_TZ_OFFSET, &offset) == ESP_OK &&
        offset >= -720 && offset <= 840) {
        settings->offset_minutes = offset;
    }
    if (nvs_get_u8(handle, NVS_TZ_DST, &dst) == ESP_OK) {
        settings->european_dst = dst != 0;
    }
    nvs_close(handle);
}

bool device_settings_save_time(const device_time_settings_t *settings)
{
    if (!settings || settings->offset_minutes < -720 ||
        settings->offset_minutes > 840 ||
        settings->offset_minutes % 30 != 0) return false;
    nvs_handle_t handle;
    if (nvs_open(NVS_NAMESPACE, NVS_READWRITE, &handle) != ESP_OK) return false;
    esp_err_t result = nvs_set_i16(handle, NVS_TZ_OFFSET,
                                   (int16_t)settings->offset_minutes);
    if (result == ESP_OK) {
        result = nvs_set_u8(handle, NVS_TZ_DST,
                            settings->european_dst ? 1 : 0);
    }
    if (result == ESP_OK) result = nvs_commit(handle);
    nvs_close(handle);
    return result == ESP_OK;
}

void device_settings_apply_time(const device_time_settings_t *settings)
{
    device_time_settings_t fallback;
    if (!settings) {
        device_settings_load_time(&fallback);
        settings = &fallback;
    }
    int absolute = settings->offset_minutes < 0
                       ? -settings->offset_minutes
                       : settings->offset_minutes;
    char timezone[80];
    snprintf(timezone, sizeof(timezone), "FST%s%d:%02d%s",
             settings->offset_minutes > 0 ? "-" :
             settings->offset_minutes < 0 ? "+" : "",
             absolute / 60, absolute % 60,
             settings->european_dst
                 ? "FDT,M3.5.0/2,M10.5.0/3"
                 : "");
    setenv("TZ", timezone, 1);
    tzset();
}

bool device_settings_factory_reset(void)
{
    nvs_handle_t handle;
    esp_err_t result = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &handle);
    if (result == ESP_ERR_NVS_NOT_FOUND) return true;
    if (result != ESP_OK) return false;
    result = nvs_erase_all(handle);
    if (result == ESP_OK) result = nvs_commit(handle);
    nvs_close(handle);
    return result == ESP_OK;
}
