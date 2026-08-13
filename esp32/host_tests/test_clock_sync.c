#include <assert.h>
#include <stdint.h>
#include <stdio.h>

#include "../main/clock_sync.h"

int main(void)
{
    int64_t epoch = 0;
    assert(clock_sync_parse_iso8601("2026-08-13T08:00:30+02:00", &epoch));
    assert(epoch == 1786600830);
    assert(clock_sync_parse_iso8601("2026-08-13T06:00:30Z", &epoch));
    assert(epoch == 1786600830);
    assert(!clock_sync_parse_iso8601("2026-99-13T06:00:30Z", &epoch));
    assert(!clock_sync_parse_iso8601("not-a-date", &epoch));
    puts("clock_sync tests passed");
    return 0;
}
