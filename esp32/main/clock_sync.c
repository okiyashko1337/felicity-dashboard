#include "clock_sync.h"

#include <stdio.h>
#include <sys/time.h>
#include <time.h>

static bool clock_synced;

static int64_t days_from_civil(int year, unsigned month, unsigned day)
{
    year -= month <= 2;
    int era = (year >= 0 ? year : year - 399) / 400;
    unsigned yoe = (unsigned)(year - era * 400);
    unsigned shifted_month = (unsigned)((int)month + (month > 2 ? -3 : 9));
    unsigned doy = (153 * shifted_month + 2) / 5 + day - 1;
    unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    return (int64_t)era * 146097 + (int64_t)doe - 719468;
}

bool clock_sync_parse_iso8601(const char *timestamp, int64_t *epoch_seconds)
{
    int year, month, day, hour, minute, second;
    if (!timestamp || !epoch_seconds ||
        sscanf(timestamp, "%d-%d-%dT%d:%d:%d", &year, &month, &day, &hour,
               &minute, &second) != 6 ||
        year < 2023 || month < 1 || month > 12 || day < 1 || day > 31 ||
        hour < 0 || hour > 23 || minute < 0 || minute > 59 || second < 0 ||
        second > 60) {
        return false;
    }
    int64_t epoch = days_from_civil(year, (unsigned)month, (unsigned)day) * 86400 +
                    hour * 3600 + minute * 60 + second;
    const char *zone = timestamp + 19;
    while (*zone && *zone != '+' && *zone != '-' && *zone != 'Z') ++zone;
    if (*zone == '+' || *zone == '-') {
        int offset_hour = 0, offset_minute = 0;
        if (sscanf(zone + 1, "%d:%d", &offset_hour, &offset_minute) != 2 ||
            offset_hour > 23 || offset_minute > 59) {
            return false;
        }
        int offset = offset_hour * 3600 + offset_minute * 60;
        epoch += *zone == '-' ? offset : -offset;
    } else if (*zone != 'Z') {
        return false;
    }
    *epoch_seconds = epoch;
    return true;
}

bool clock_sync_from_iso8601_once(const char *timestamp)
{
    int64_t epoch = 0;
    if (!clock_sync_parse_iso8601(timestamp, &epoch)) return false;
    time_t current = time(NULL);
    if (!clock_synced || current < 1700000000) {
        struct timeval value = {.tv_sec = (time_t)epoch, .tv_usec = 0};
        if (settimeofday(&value, NULL) != 0) return false;
        clock_synced = true;
    }
    return true;
}
