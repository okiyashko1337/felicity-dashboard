#include "device_settings.h"

#include <stdio.h>
#include <string.h>

#include "nvs.h"
#include "sdkconfig.h"

static bool read_string(nvs_handle_t handle, const char *key, char *value, size_t capacity)
{
    size_t length = capacity;
    esp_err_t result = nvs_get_str(handle, key, value, &length);
    if (result == ESP_ERR_NVS_NOT_FOUND) {
        value[0] = '\0';
        return true;
    }
    return result == ESP_OK;
}

bool device_settings_load(device_settings_t *settings)
{
    memset(settings, 0, sizeof(*settings));
    snprintf(settings->api_base_url, sizeof(settings->api_base_url), "%s",
             CONFIG_FELICITY_API_BASE_URL);
    nvs_handle_t handle;
    esp_err_t result = nvs_open("felicity", NVS_READONLY, &handle);
    if (result == ESP_ERR_NVS_NOT_FOUND) return true;
    if (result != ESP_OK) return false;
    bool ok = read_string(handle, "ssid", settings->wifi_ssid,
                          sizeof(settings->wifi_ssid)) &&
              read_string(handle, "password", settings->wifi_password,
                          sizeof(settings->wifi_password));
    char api[sizeof(settings->api_base_url)] = {0};
    if (ok && read_string(handle, "api", api, sizeof(api)) && api[0]) {
        snprintf(settings->api_base_url, sizeof(settings->api_base_url), "%s", api);
    }
    nvs_close(handle);
    return ok;
}

bool device_settings_save(const device_settings_t *settings)
{
    nvs_handle_t handle;
    if (nvs_open("felicity", NVS_READWRITE, &handle) != ESP_OK) return false;
    esp_err_t result = nvs_set_str(handle, "ssid", settings->wifi_ssid);
    if (result == ESP_OK) result = nvs_set_str(handle, "password", settings->wifi_password);
    if (result == ESP_OK) result = nvs_set_str(handle, "api", settings->api_base_url);
    if (result == ESP_OK) result = nvs_commit(handle);
    nvs_close(handle);
    return result == ESP_OK;
}

bool device_settings_clear(void)
{
    nvs_handle_t handle;
    if (nvs_open("felicity", NVS_READWRITE, &handle) != ESP_OK) return false;
    esp_err_t result = nvs_erase_all(handle);
    if (result == ESP_OK) result = nvs_commit(handle);
    nvs_close(handle);
    return result == ESP_OK;
}
