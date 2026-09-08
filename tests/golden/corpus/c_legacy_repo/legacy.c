#include <stdio.h>
#include <string.h>

static void fill(char *dst, const char *src) {
    sprintf(dst, "%s", src);
    strcpy(dst, src);
}

int main(void) {
    register int i = 0;
    char buf[64];
    gets(buf);
    return i;
}
