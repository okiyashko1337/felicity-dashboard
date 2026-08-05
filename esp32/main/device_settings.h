#pragma once

#include <stdbool.h>
#include <stddef.h>

#define FELICITY_HA_HOST_MAX 64
#define FELICITY_API_URL_MAX 96

typedef struct {
    int offset_minutes;
    bool european_dst;
} device_time_settings_t;

/* The UI stores only a friendly hostname or IPv4 address. Protocol, API port
 * and paths remain firmware implementation details. */
bool device_settings_load_ha_host(char *output, size_t capacity);
bool device_settings_save_ha_host(const char *host);
bool device_settings_ha_host_valid(const char *host);
void device_settings_build_api_url(const char *host, char *output,
                                   size_t capacity);
/* Resolves .local explicitly to IPv4 with a bounded mDNS timeout. This keeps
 * HTTP requests and the local touchscreen responsive when HA is offline. */
bool device_settings_prepare_api_url(const char *host, char *output,
                                     size_t capacity);
void device_settings_load_time(device_time_settings_t *settings);
bool device_settings_save_time(const device_time_settings_t *settings);
void device_settings_apply_time(const device_time_settings_t *settings);
bool device_settings_factory_reset(void);
