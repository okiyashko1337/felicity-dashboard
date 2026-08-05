#include "wifi_portal.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "device_settings.h"
#include "wifi_manager.h"

static const char *TAG = "wifi_portal";

static const char SETUP_PAGE[] =
    "<!doctype html><meta name=viewport content='width=device-width'>"
    "<style>body{font:17px system-ui;max-width:38rem;margin:2rem auto;padding:1rem;"
    "background:#041712;color:#eee}label{display:block;margin:1rem 0}input{width:100%%;"
    "box-sizing:border-box;padding:.7rem;font-size:1rem}button{padding:.8rem 1.2rem;"
    "font-size:1rem;background:#34d399;border:0;border-radius:.4rem}pre{min-height:13rem;"
    "padding:1rem;background:#092b22;color:#d1fae5;white-space:pre-wrap}</style>"
    "<h1>Felicity Wi-Fi</h1><p>ESP32 remains available at <b>192.168.4.1</b> while connecting.</p>"
    "<form method=post action=/save>"
    "<label>Wi-Fi network<input name=ssid maxlength=32 required></label>"
    "<label>Wi-Fi password<input name=password type=password maxlength=63></label>"
    "<button>Save and connect</button></form>"
    "<h2>Home Assistant</h2><form method=post action=/ha>"
    "<label>Address<input name=ha_host maxlength=63 required value='%s' "
    "placeholder='homeassistant.local'></label>"
    "<button>Save HA address</button></form><h2>Connection log</h2>"
    "<pre id=log>Loading...</pre><script>async function u(){try{log.textContent="
    "await(await fetch('/status',{cache:'no-store'})).text()}catch(e){log.textContent='Reconnecting...'}}"
    "u();setInterval(u,1000)</script>";

static void url_decode(char *value)
{
    char *read = value;
    char *write = value;
    while (*read) {
        if (*read == '+') {
            *write++ = ' ';
            ++read;
        } else if (*read == '%' && isxdigit((unsigned char)read[1]) &&
                   isxdigit((unsigned char)read[2])) {
            char hex[3] = {read[1], read[2], 0};
            *write++ = (char)strtol(hex, NULL, 16);
            read += 3;
        } else {
            *write++ = *read++;
        }
    }
    *write = '\0';
}

static bool form_value(const char *body, const char *key, char *output,
                       size_t capacity)
{
    if (httpd_query_key_value(body, key, output, capacity) != ESP_OK) return false;
    url_decode(output);
    return true;
}

static const char *state_name(wifi_manager_state_t state)
{
    switch (state) {
        case WIFI_MANAGER_SCANNING: return "SCANNING";
        case WIFI_MANAGER_SCAN_READY: return "SCAN READY";
        case WIFI_MANAGER_CONNECTING: return "CONNECTING";
        case WIFI_MANAGER_CONNECTED: return "CONNECTED";
        case WIFI_MANAGER_FAILED: return "FAILED";
        default: return "IDLE";
    }
}

static esp_err_t root_get(httpd_req_t *request)
{
    char ha_host[FELICITY_HA_HOST_MAX];
    char page[2300];
    device_settings_load_ha_host(ha_host, sizeof(ha_host));
    snprintf(page, sizeof(page), SETUP_PAGE, ha_host);
    httpd_resp_set_type(request, "text/html; charset=utf-8");
    return httpd_resp_send(request, page, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t status_get(httpd_req_t *request)
{
    char lines[FELICITY_WIFI_LOG_MAX_LINES][FELICITY_WIFI_LOG_LINE_MAX];
    char response[768];
    uint32_t revision = 0;
    size_t count = wifi_manager_log_snapshot(
        lines, FELICITY_WIFI_LOG_MAX_LINES, &revision);
    int used = snprintf(response, sizeof(response), "STATE: %s\n",
                        state_name(wifi_manager_state()));
    for (size_t i = 0; i < count && used > 0 && (size_t)used < sizeof(response); ++i) {
        used += snprintf(response + used, sizeof(response) - (size_t)used,
                         "%s\n", lines[i]);
    }
    httpd_resp_set_type(request, "text/plain; charset=utf-8");
    httpd_resp_set_hdr(request, "Cache-Control", "no-store");
    return httpd_resp_send(request, response, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t save_post(httpd_req_t *request)
{
    if (request->content_len <= 0 || request->content_len > 256) {
        return httpd_resp_send_err(request, HTTPD_400_BAD_REQUEST, "Invalid form");
    }
    char body[257] = {0};
    size_t total = 0;
    while (total < (size_t)request->content_len) {
        int received = httpd_req_recv(request, body + total,
                                      (size_t)request->content_len - total);
        if (received == HTTPD_SOCK_ERR_TIMEOUT) continue;
        if (received <= 0) break;
        total += (size_t)received;
    }
    char ssid[FELICITY_WIFI_SSID_MAX + 1] = {0};
    char password[FELICITY_WIFI_PASSWORD_MAX] = {0};
    bool valid = total == (size_t)request->content_len &&
                 form_value(body, "ssid", ssid, sizeof(ssid)) &&
                 form_value(body, "password", password, sizeof(password)) &&
                 ssid[0];
    if (!valid) {
        memset(password, 0, sizeof(password));
        return httpd_resp_send_err(request, HTTPD_400_BAD_REQUEST, "Invalid settings");
    }
    httpd_resp_set_type(request, "text/html; charset=utf-8");
    httpd_resp_sendstr(request,
                       "<h1>Saved</h1><p>ESP32 is restarting. Reconnect to the "
                       "Felicity setup network, then reopen 192.168.4.1.</p>");
    vTaskDelay(pdMS_TO_TICKS(500));
    wifi_manager_stage_credentials_and_restart(ssid, password);
    return ESP_OK;
}

static esp_err_t ha_post(httpd_req_t *request)
{
    if (request->content_len <= 0 || request->content_len > 256) {
        return httpd_resp_send_err(request, HTTPD_400_BAD_REQUEST, "Invalid form");
    }
    char body[257] = {0};
    size_t total = 0;
    while (total < (size_t)request->content_len) {
        int received = httpd_req_recv(request, body + total,
                                      (size_t)request->content_len - total);
        if (received == HTTPD_SOCK_ERR_TIMEOUT) continue;
        if (received <= 0) break;
        total += (size_t)received;
    }
    char ha_host[FELICITY_HA_HOST_MAX] = {0};
    bool valid = total == (size_t)request->content_len &&
                 form_value(body, "ha_host", ha_host, sizeof(ha_host)) &&
                 device_settings_save_ha_host(ha_host);
    if (!valid) {
        return httpd_resp_send_err(request, HTTPD_400_BAD_REQUEST,
                                   "Use a hostname or IPv4 address");
    }
    httpd_resp_set_type(request, "text/html; charset=utf-8");
    httpd_resp_sendstr(request,
                       "<h1>HA address saved</h1><p>ESP32 is restarting.</p>");
    vTaskDelay(pdMS_TO_TICKS(500));
    esp_restart();
    return ESP_OK;
}

void wifi_portal_start(void)
{
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    httpd_handle_t server = NULL;
    ESP_ERROR_CHECK(httpd_start(&server, &config));
    httpd_uri_t root = {.uri = "/", .method = HTTP_GET, .handler = root_get};
    httpd_uri_t status = {.uri = "/status", .method = HTTP_GET, .handler = status_get};
    httpd_uri_t save = {.uri = "/save", .method = HTTP_POST, .handler = save_post};
    httpd_uri_t ha = {.uri = "/ha", .method = HTTP_POST, .handler = ha_post};
    ESP_ERROR_CHECK(httpd_register_uri_handler(server, &root));
    ESP_ERROR_CHECK(httpd_register_uri_handler(server, &status));
    ESP_ERROR_CHECK(httpd_register_uri_handler(server, &save));
    ESP_ERROR_CHECK(httpd_register_uri_handler(server, &ha));
    ESP_LOGI(TAG, "Portal ready at http://192.168.4.1");
}
