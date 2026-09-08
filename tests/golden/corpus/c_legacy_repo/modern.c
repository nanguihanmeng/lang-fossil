#include <stdio.h>
#include <string.h>

static void fill(char *dst, size_t n, const char *src) {
    snprintf(dst, n, "%s", src);
}

int main(void) {
    char buf[64];
    if (fgets(buf, sizeof buf, stdin) != NULL) {
        puts(buf);
    }
    return 0;
}
