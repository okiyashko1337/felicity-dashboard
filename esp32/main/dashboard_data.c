#include "dashboard_data.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cJSON.h"
#include "esp_http_client.h"
#include "esp_log.h"

static const char *TAG = "dashboard_api";

typedef struct {
    char *data;
    size_t length;
    size_t capacity;
} response_buffer_t;

static esp_err_t http_event(esp_http_client_event_t *event)
{
    response_buffer_t *buffer = event->user_data;
    if (event->event_id != HTTP_EVENT_ON_DATA || event->data_len <= 0) {
        return ESP_OK;
    }
    size_t required = buffer->length + (size_t)event->data_len + 1;
    if (required > buffer->capacity) {
        size_t capacity = required + 512;
        char *next = realloc(buffer->data, capacity);
        if (!next) {
            return ESP_ERR_NO_MEM;
        }
        buffer->data = next;
        buffer->capacity = capacity;
    }
    memcpy(buffer->data + buffer->length, event->data, event->data_len);
    buffer->length += event->data_len;
    buffer->data[buffer->length] = '\0';
    return ESP_OK;
}

static float json_number(cJSON *root, const char *group, const char *name)
{
    cJSON *parent = group ? cJSON_GetObjectItemCaseSensitive(root, group) : root;
    cJSON *item = parent ? cJSON_GetObjectItemCaseSensitive(parent, name) : NULL;
    return cJSON_IsNumber(item) ? (float)item->valuedouble : 0.0f;
}

void dashboard_sample_snapshot(dashboard_snapshot_t *s)
{
    *s = (dashboard_snapshot_t){
        .pv_total_w = 3480, .pv1_w = 1770, .pv2_w = 1710,
        .load_total_w = 1240, .load_l1_w = 410, .load_l2_w = 390, .load_l3_w = 440,
        .battery_soc = 74, .battery_voltage_v = 52.4f, .battery_power_w = 920,
        .grid_voltage_l1_v = 230.2f, .grid_voltage_l2_v = 231.0f,
        .grid_voltage_l3_v = 229.7f, .grid_power_w = -1320,
        .grid_frequency_hz = 50.0f,
    };
    snprintf(s->timestamp, sizeof(s->timestamp), "2026-08-02T11:30:00+02:00");
}

bool dashboard_parse_current(const char *json, dashboard_snapshot_t *s)
{
    cJSON *document = cJSON_Parse(json);
    if (!document) {
        return false;
    }
    cJSON *parsed = cJSON_GetObjectItemCaseSensitive(document, "parsed");
    if (!cJSON_IsObject(parsed)) {
        cJSON_Delete(document);
        return false;
    }

    memset(s, 0, sizeof(*s));
    s->pv_total_w = json_number(parsed, "pv_power_w", "total");
    s->pv1_w = json_number(parsed, "pv_power_w", "pv1");
    s->pv2_w = json_number(parsed, "pv_power_w", "pv2");
    s->load_total_w = json_number(parsed, "load_power_w", "total");
    s->load_l1_w = json_number(parsed, "load_power_w", "l1");
    s->load_l2_w = json_number(parsed, "load_power_w", "l2");
    s->load_l3_w = json_number(parsed, "load_power_w", "l3");
    s->battery_soc = json_number(parsed, NULL, "soc_percent");
    s->battery_voltage_v = json_number(parsed, NULL, "battery_voltage_v");
    s->battery_power_w = json_number(parsed, NULL, "battery_power_w");
    s->grid_voltage_l1_v = json_number(parsed, "grid_voltage_v", "l1");
    s->grid_voltage_l2_v = json_number(parsed, "grid_voltage_v", "l2");
    s->grid_voltage_l3_v = json_number(parsed, "grid_voltage_v", "l3");
    s->grid_power_w = json_number(parsed, "grid_power_w", "total");
    s->grid_frequency_hz = json_number(parsed, NULL, "grid_frequency_hz");

    cJSON *timestamp = cJSON_GetObjectItemCaseSensitive(document, "timestamp");
    if (cJSON_IsString(timestamp)) {
        snprintf(s->timestamp, sizeof(s->timestamp), "%s", timestamp->valuestring);
    }
    cJSON_Delete(document);
    return true;
}

bool dashboard_fetch_current(const char *base_url, dashboard_snapshot_t *snapshot)
{
    char url[192];
    snprintf(url, sizeof(url), "%s/api/device/current", base_url);
    response_buffer_t response = {0};
    esp_http_client_config_t config = {
        .url = url,
        .event_handler = http_event,
        .user_data = &response,
        .timeout_ms = 4000,
    };
    esp_http_client_handle_t client = esp_http_client_init(&config);
    esp_err_t result = esp_http_client_perform(client);
    int status = esp_http_client_get_status_code(client);
    esp_http_client_cleanup(client);

    bool ok = result == ESP_OK && status == 200 && response.data &&
              dashboard_parse_current(response.data, snapshot);
    if (!ok) {
        ESP_LOGW(TAG, "GET %s failed: %s, HTTP %d", url, esp_err_to_name(result), status);
    }
    free(response.data);
    return ok;
}

void dashboard_sample_chart(const char *metric, dashboard_chart_t *chart)
{
    memset(chart, 0, sizeof(*chart));
    chart->count = 24;
    chart->channels = strcmp(metric, "pv") == 0 ? 3 :
                      strcmp(metric, "battery") == 0 ? 2 : 4;
    if (strcmp(metric, "today") == 0) chart->channels = 2;
    for (size_t i = 0; i < chart->count; ++i) {
        float phase = (float)i / (float)(chart->count - 1);
        if (strcmp(metric, "battery") == 0) {
            chart->samples[i][0] = 68.0f + phase * 12.0f;
            chart->samples[i][1] = 800.0f - phase * 1600.0f;
        } else if (strcmp(metric, "grid") == 0) {
            chart->samples[i][0] = 229.0f + phase * 2.0f;
            chart->samples[i][1] = 231.0f - phase;
            chart->samples[i][2] = 230.0f + phase;
            chart->samples[i][3] = -1400.0f + phase * 900.0f;
        } else if (strcmp(metric, "system") == 0) {
            chart->samples[i][0] = 18.0f + phase * 14.0f;
            chart->samples[i][1] = 42.0f + phase * 3.0f;
            chart->samples[i][2] = 51.0f + phase * 2.0f;
            chart->samples[i][3] = 36.0f;
        } else {
            float total = 800.0f + phase * 4200.0f;
            chart->samples[i][0] = total;
            chart->samples[i][1] = total * 0.52f;
            chart->samples[i][2] = total * 0.48f;
            chart->samples[i][3] = total * 0.34f;
        }
    }
}

bool dashboard_fetch_chart(const char *base_url, const char *metric, dashboard_chart_t *chart)
{
    char url[224];
    snprintf(url, sizeof(url), "%s/api/device/chart?metric=%s&limit=%d",
             base_url, metric, DASHBOARD_CHART_MAX_SAMPLES);
    response_buffer_t response = {0};
    esp_http_client_config_t config = {
        .url = url, .event_handler = http_event, .user_data = &response, .timeout_ms = 5000,
    };
    esp_http_client_handle_t client = esp_http_client_init(&config);
    esp_err_t result = esp_http_client_perform(client);
    int status = esp_http_client_get_status_code(client);
    esp_http_client_cleanup(client);
    if (result != ESP_OK || status != 200 || !response.data) {
        ESP_LOGW(TAG, "GET chart %s failed: %s, HTTP %d", metric, esp_err_to_name(result), status);
        free(response.data);
        return false;
    }

    cJSON *document = cJSON_Parse(response.data);
    free(response.data);
    cJSON *samples = document ? cJSON_GetObjectItemCaseSensitive(document, "samples") : NULL;
    if (!cJSON_IsArray(samples)) {
        cJSON_Delete(document);
        return false;
    }
    memset(chart, 0, sizeof(*chart));
    cJSON *row = NULL;
    cJSON_ArrayForEach(row, samples) {
        if (chart->count >= DASHBOARD_CHART_MAX_SAMPLES || !cJSON_IsArray(row)) break;
        size_t channel = 0;
        cJSON *item = NULL;
        cJSON_ArrayForEach(item, row) {
            if (channel >= DASHBOARD_CHART_MAX_CHANNELS) break;
            chart->samples[chart->count][channel++] = cJSON_IsNumber(item) ? (float)item->valuedouble : 0.0f;
        }
        if (chart->count == 0) chart->channels = channel;
        chart->count++;
    }
    cJSON_Delete(document);
    return chart->count > 0 && chart->channels > 0;
}

void dashboard_sample_gaps(dashboard_gaps_t *gaps)
{
    memset(gaps, 0, sizeof(*gaps));
    gaps->coverage_percent = 98.7f;
    gaps->gap_count = 2;
    gaps->longest_gap_seconds = 94;
    snprintf(gaps->latest_start, sizeof(gaps->latest_start), "2026-08-02T10:21:00+02:00");
    snprintf(gaps->latest_end, sizeof(gaps->latest_end), "2026-08-02T10:22:34+02:00");
    gaps->chart.count = 24;
    gaps->chart.channels = 1;
    for (size_t i = 0; i < gaps->chart.count; ++i) {
        gaps->chart.samples[i][0] = (i == 9 || i == 17) ? 35.0f : 100.0f;
    }
}

bool dashboard_fetch_gaps(const char *base_url, dashboard_gaps_t *gaps)
{
    char url[224];
    snprintf(url, sizeof(url), "%s/api/device/gaps?bins=%d",
             base_url, DASHBOARD_CHART_MAX_SAMPLES);
    response_buffer_t response = {0};
    esp_http_client_config_t config = {
        .url = url, .event_handler = http_event, .user_data = &response, .timeout_ms = 15000,
    };
    esp_http_client_handle_t client = esp_http_client_init(&config);
    esp_err_t result = esp_http_client_perform(client);
    int status = esp_http_client_get_status_code(client);
    esp_http_client_cleanup(client);
    if (result != ESP_OK || status != 200 || !response.data) {
        ESP_LOGW(TAG, "GET gaps failed: %s, HTTP %d", esp_err_to_name(result), status);
        free(response.data);
        return false;
    }

    cJSON *document = cJSON_Parse(response.data);
    free(response.data);
    cJSON *samples = document ? cJSON_GetObjectItemCaseSensitive(document, "samples") : NULL;
    if (!cJSON_IsArray(samples)) {
        cJSON_Delete(document);
        return false;
    }
    memset(gaps, 0, sizeof(*gaps));
    gaps->coverage_percent = json_number(document, NULL, "coverage_percent");
    gaps->gap_count = (int)json_number(document, NULL, "gap_count");
    gaps->longest_gap_seconds = (int)json_number(document, NULL, "longest_gap_seconds");
    cJSON *latest_start = cJSON_GetObjectItemCaseSensitive(document, "latest_start");
    cJSON *latest_end = cJSON_GetObjectItemCaseSensitive(document, "latest_end");
    if (cJSON_IsString(latest_start)) {
        snprintf(gaps->latest_start, sizeof(gaps->latest_start), "%s", latest_start->valuestring);
    }
    if (cJSON_IsString(latest_end)) {
        snprintf(gaps->latest_end, sizeof(gaps->latest_end), "%s", latest_end->valuestring);
    }
    cJSON *row = NULL;
    cJSON_ArrayForEach(row, samples) {
        if (gaps->chart.count >= DASHBOARD_CHART_MAX_SAMPLES || !cJSON_IsArray(row)) break;
        cJSON *item = cJSON_GetArrayItem(row, 0);
        gaps->chart.samples[gaps->chart.count++][0] =
            cJSON_IsNumber(item) ? (float)item->valuedouble : 0.0f;
    }
    gaps->chart.channels = gaps->chart.count ? 1 : 0;
    cJSON_Delete(document);
    return gaps->chart.count > 0;
}
