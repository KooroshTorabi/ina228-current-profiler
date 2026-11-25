/* Minimal newlib stubs: the firmware uses no files, heap or stdio. */
#include <sys/stat.h>
#include <errno.h>
int _close(int f) { (void)f; return -1; }
int _lseek(int f, int o, int w) { (void)f; (void)o; (void)w; return 0; }
int _read(int f, char *p, int n) { (void)f; (void)p; (void)n; return 0; }
int _write(int f, const char *p, int n) { (void)f; (void)p; return n; }
int _fstat(int f, struct stat *st) { (void)f; st->st_mode = S_IFCHR; return 0; }
int _isatty(int f) { (void)f; return 1; }
int _getpid(void) { return 1; }
int _kill(int p, int s) { (void)p; (void)s; errno = EINVAL; return -1; }
void _exit(int s) { (void)s; for (;;) {} }
void *_sbrk(int n) { (void)n; errno = ENOMEM; return (void *)-1; }
