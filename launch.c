#ifndef _WIN32
#define _POSIX_C_SOURCE 200809L
#endif
// vibe coded file ahead
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <process.h>
#include <direct.h>
#include <io.h>
#include <sys/stat.h>
#include <sys/types.h>
#else
#include <dirent.h>
#include <fcntl.h>
#include <signal.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#include <pwd.h>
#endif

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define PATH_CAPACITY 32768
#define FOOTER_SIZE 16

static const unsigned char header_magic[8] = {'P', 'Y', 'T', 'H', 'I', 'N', 'G', '1'};
static const unsigned char footer_magic[8] = {'P', 'Y', 'T', 'H', 'E', 'N', 'D', '1'};

static void encode_u32(unsigned char out[4], uint32_t value) {
    for (int i = 0; i < 4; i++) out[i] = (unsigned char)(value >> (i * 8));
}

static void encode_u64(unsigned char out[8], uint64_t value) {
    for (int i = 0; i < 8; i++) out[i] = (unsigned char)(value >> (i * 8));
}

static uint32_t decode_u32(const unsigned char in[4]) {
    uint32_t value = 0;
    for (int i = 0; i < 4; i++) value |= (uint32_t)in[i] << (i * 8);
    return value;
}

static uint64_t decode_u64(const unsigned char in[8]) {
    uint64_t value = 0;
    for (int i = 0; i < 8; i++) value |= (uint64_t)in[i] << (i * 8);
    return value;
}

static int write_all(FILE *file, const void *data, size_t size) {
    return size == 0 || fwrite(data, 1, size, file) == size;
}

static int read_all(FILE *file, void *data, size_t size) {
    return size == 0 || fread(data, 1, size, file) == size;
}

static int file_size(FILE *file, uint64_t *size) {
#ifdef _WIN32
    if (_fseeki64(file, 0, SEEK_END) != 0) return 0;
    __int64 end = _ftelli64(file);
#else
    if (fseeko(file, 0, SEEK_END) != 0) return 0;
    off_t end = ftello(file);
#endif
    if (end < 0) return 0;
    *size = (uint64_t)end;
    return 1;
}

static int write_entry(FILE *output, const char *path, const char *full_path,
                       uint64_t *archive_size) {
    FILE *input = fopen(full_path, "rb");
    if (input == NULL) {
        fprintf(stderr, "Cannot read package file %s: %s\n", full_path, strerror(errno));
        return 0;
    }
    uint64_t size;
    if (!file_size(input, &size)) {
        fclose(input);
        fprintf(stderr, "Cannot determine size of %s\n", full_path);
        return 0;
    }
#ifdef _WIN32
    if (_fseeki64(input, 0, SEEK_SET) != 0) {
#else
    if (fseeko(input, 0, SEEK_SET) != 0) {
#endif
        fclose(input);
        return 0;
    }
    size_t path_length = strlen(path);
    if (path_length == 0 || path_length > UINT32_MAX) {
        fclose(input);
        fprintf(stderr, "Invalid package path: %s\n", path);
        return 0;
    }

    unsigned char fields[16];
    encode_u32(fields, (uint32_t)path_length);
    encode_u64(fields + 4, size);
#ifdef _WIN32
    encode_u32(fields + 12, 0755);
#else
    struct stat info;
    encode_u32(fields + 12, stat(full_path, &info) == 0 ? (uint32_t)(info.st_mode & 0777) : 0644);
#endif
    if (!write_all(output, fields, sizeof(fields)) || !write_all(output, path, path_length)) {
        fclose(input);
        return 0;
    }
    *archive_size += sizeof(fields) + path_length;

    unsigned char buffer[65536];
    uint64_t remaining = size;
    while (remaining > 0) {
        size_t amount = remaining > sizeof(buffer) ? sizeof(buffer) : (size_t)remaining;
        size_t actual = fread(buffer, 1, amount, input);
        if (actual != amount || !write_all(output, buffer, amount)) {
            fclose(input);
            fprintf(stderr, "Could not append package file %s\n", full_path);
            return 0;
        }
        remaining -= amount;
        *archive_size += amount;
    }
    fclose(input);
    return 1;
}

#ifndef _WIN32
static int add_directory(FILE *output, const char *root, const char *relative,
                         uint64_t *archive_size) {
    char directory[PATH_CAPACITY];
    if (relative[0] == '\0') {
        if (snprintf(directory, sizeof(directory), "%s", root) >= (int)sizeof(directory)) return 0;
    } else if (snprintf(directory, sizeof(directory), "%s/%s", root, relative) >= (int)sizeof(directory)) {
        return 0;
    }
    DIR *handle = opendir(directory);
    if (handle == NULL) {
        fprintf(stderr, "Cannot open package directory %s: %s\n", directory, strerror(errno));
        return 0;
    }

    struct dirent *entry;
    int success = 1;
    while (success && (entry = readdir(handle)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) continue;
        char child_relative[PATH_CAPACITY], child_full[PATH_CAPACITY];
        int a = relative[0] == '\0'
                    ? snprintf(child_relative, sizeof(child_relative), "%s", entry->d_name)
                    : snprintf(child_relative, sizeof(child_relative), "%s/%s", relative, entry->d_name);
        int b = snprintf(child_full, sizeof(child_full), "%s/%s", root, child_relative);
        if (a < 0 || a >= (int)sizeof(child_relative) || b < 0 || b >= (int)sizeof(child_full)) {
            success = 0;
            break;
        }
        struct stat info;
        if (lstat(child_full, &info) != 0) {
            success = 0;
        } else if (S_ISDIR(info.st_mode)) {
            success = add_directory(output, root, child_relative, archive_size);
        } else if (S_ISREG(info.st_mode)) {
            success = write_entry(output, child_relative, child_full, archive_size);
        }
    }
    closedir(handle);
    return success;
}
#else
static int add_directory(FILE *output, const char *root, const char *relative,
                         uint64_t *archive_size) {
    char directory[PATH_CAPACITY], pattern[PATH_CAPACITY];
    if (relative[0] == '\0')
        snprintf(directory, sizeof(directory), "%s", root);
    else if (snprintf(directory, sizeof(directory), "%s\\%s", root, relative) >= (int)sizeof(directory))
        return 0;
    if (snprintf(pattern, sizeof(pattern), "%s\\*", directory) >= (int)sizeof(pattern)) return 0;

    WIN32_FIND_DATAA data;
    HANDLE handle = FindFirstFileA(pattern, &data);
    if (handle == INVALID_HANDLE_VALUE) {
        fprintf(stderr, "Cannot open package directory %s\n", directory);
        return 0;
    }
    int success = 1;
    do {
        if (strcmp(data.cFileName, ".") == 0 || strcmp(data.cFileName, "..") == 0) continue;
        char child_relative[PATH_CAPACITY], child_full[PATH_CAPACITY];
        int a = relative[0] == '\0'
                    ? snprintf(child_relative, sizeof(child_relative), "%s", data.cFileName)
                    : snprintf(child_relative, sizeof(child_relative), "%s/%s", relative, data.cFileName);
        int b = snprintf(child_full, sizeof(child_full), "%s\\%s", root, child_relative);
        if (a < 0 || a >= (int)sizeof(child_relative) || b < 0 || b >= (int)sizeof(child_full)) {
            success = 0;
            break;
        }
        if (data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)
            success = add_directory(output, root, child_relative, archive_size);
        else
            success = write_entry(output, child_relative, child_full, archive_size);
    } while (success && FindNextFileA(handle, &data));
    FindClose(handle);
    return success;
}
#endif

static int copy_file(FILE *output, FILE *input) {
    unsigned char buffer[65536];
    size_t amount;
    while ((amount = fread(buffer, 1, sizeof(buffer), input)) > 0) {
        if (!write_all(output, buffer, amount)) return 0;
    }
    return !ferror(input);
}

static int make_package(const char *self, const char *root, const char *destination) {
    FILE *source = fopen(self, "rb");
    FILE *output = fopen(destination, "wb");
    if (source == NULL || output == NULL) {
        fprintf(stderr, "Could not open launcher or output package: %s\n", strerror(errno));
        if (source) fclose(source);
        if (output) fclose(output);
        return 1;
    }
    if (!copy_file(output, source)) {
        fprintf(stderr, "Could not copy launcher executable.\n");
        fclose(source);
        fclose(output);
        return 1;
    }
    fclose(source);

    uint64_t archive_size = 0;
    int success = write_all(output, header_magic, sizeof(header_magic));
    archive_size += sizeof(header_magic);
    if (success) success = add_directory(output, root, "", &archive_size);
    unsigned char terminator[4] = {0, 0, 0, 0};
    if (success) {
        success = write_all(output, terminator, sizeof(terminator));
        archive_size += sizeof(terminator);
    }
    unsigned char footer[FOOTER_SIZE];
    memcpy(footer, footer_magic, sizeof(footer_magic));
    encode_u64(footer + 8, archive_size);
    if (success) success = write_all(output, footer, sizeof(footer));
    if (fclose(output) != 0) success = 0;
    if (!success) {
        fprintf(stderr, "Could not create self-extracting package.\n");
        remove(destination);
        return 1;
    }
#ifdef _WIN32
    _chmod(destination, _S_IREAD | _S_IWRITE | _S_IEXEC);
#else
    chmod(destination, 0755);
#endif
    return 0;
}

static int valid_relative_path(const char *path, size_t length) {
    if (length == 0 || path[0] == '/' || path[0] == '\\') return 0;
    if (length >= 2 && path[1] == ':') return 0;
    size_t segment_start = 0;
    for (size_t i = 0; i <= length; i++) {
        if (i == length || path[i] == '/' || path[i] == '\\') {
            size_t segment_length = i - segment_start;
            if (segment_length == 0 || (segment_length == 1 && path[segment_start] == '.') ||
                (segment_length == 2 && path[segment_start] == '.' && path[segment_start + 1] == '.'))
                return 0;
            segment_start = i + 1;
        }
    }
    return 1;
}

static int join_path(char *out, size_t capacity, const char *root, const char *relative) {
#ifdef _WIN32
    int length = snprintf(out, capacity, "%s\\%s", root, relative);
    for (char *p = out; *p; p++) if (*p == '/') *p = '\\';
#else
    int length = snprintf(out, capacity, "%s/%s", root, relative);
#endif
    return length >= 0 && (size_t)length < capacity;
}

static int make_directories_for(const char *root, const char *relative) {
    char path[PATH_CAPACITY];
    if (!join_path(path, sizeof(path), root, relative)) return 0;
    for (char *p = path + strlen(root) + 1; *p; p++) {
        if (*p == '/' || *p == '\\') {
            char separator = *p;
            *p = '\0';
#ifdef _WIN32
            CreateDirectoryA(path, NULL);
#else
            if (mkdir(path, 0755) != 0 && errno != EEXIST) return 0;
#endif
            *p = separator;
        }
    }
    return 1;
}

static int extract_archive(FILE *executable, uint64_t total_size, const char *root) {
    if (total_size < FOOTER_SIZE) return 0;
#ifdef _WIN32
    if (_fseeki64(executable, (__int64)(total_size - FOOTER_SIZE), SEEK_SET) != 0) return 0;
#else
    if (fseeko(executable, (off_t)(total_size - FOOTER_SIZE), SEEK_SET) != 0) return 0;
#endif
    unsigned char footer[FOOTER_SIZE];
    if (!read_all(executable, footer, sizeof(footer)) ||
        memcmp(footer, footer_magic, sizeof(footer_magic)) != 0) return 0;
    uint64_t archive_size = decode_u64(footer + 8);
    if (archive_size > total_size - FOOTER_SIZE) return 0;
    uint64_t archive_start = total_size - FOOTER_SIZE - archive_size;
#ifdef _WIN32
    if (_fseeki64(executable, (__int64)archive_start, SEEK_SET) != 0) return 0;
#else
    if (fseeko(executable, (off_t)archive_start, SEEK_SET) != 0) return 0;
#endif
    unsigned char magic[8];
    if (!read_all(executable, magic, sizeof(magic)) || memcmp(magic, header_magic, sizeof(magic)) != 0)
        return 0;
    uint64_t remaining = archive_size - sizeof(magic);
    while (remaining >= 4) {
        unsigned char fields[16];
        if (!read_all(executable, fields, 4)) return 0;
        remaining -= 4;
        uint32_t path_length = decode_u32(fields);
        if (path_length == 0) return 1;
        if (remaining < 12 || path_length > PATH_CAPACITY - 1) return 0;
        if (!read_all(executable, fields + 4, 12)) return 0;
        remaining -= 12;
        uint64_t size = decode_u64(fields + 4);
        uint32_t mode = decode_u32(fields + 12);
        if (remaining < path_length || size > remaining - path_length) return 0;
        char relative[PATH_CAPACITY];
        if (!read_all(executable, relative, path_length)) return 0;
        relative[path_length] = '\0';
        remaining -= path_length;
        if (!valid_relative_path(relative, path_length)) return 0;

        char output_path[PATH_CAPACITY];
        if (!join_path(output_path, sizeof(output_path), root, relative) ||
            !make_directories_for(root, relative)) return 0;
        FILE *output = fopen(output_path, "wb");
        if (output == NULL) return 0;
        unsigned char buffer[65536];
        uint64_t file_remaining = size;
        while (file_remaining > 0) {
            size_t amount = file_remaining > sizeof(buffer) ? sizeof(buffer) : (size_t)file_remaining;
            if (!read_all(executable, buffer, amount) || !write_all(output, buffer, amount)) {
                fclose(output);
                return 0;
            }
            file_remaining -= amount;
        }
        fclose(output);
        remaining -= size;
#ifndef _WIN32
        chmod(output_path, mode & 0777);
#else
        (void)mode;
#endif
    }
    return 0;
}

#ifdef _WIN32
static int create_temp_directory(char *path, size_t capacity) {
    char base[PATH_CAPACITY], temporary[PATH_CAPACITY];
    DWORD length = GetTempPathA((DWORD)sizeof(base), base);
    if (length == 0 || length >= sizeof(base)) return 0;
    if (GetTempFileNameA(base, "pyt", 0, temporary) == 0) return 0;
    DeleteFileA(temporary);
    if (!CreateDirectoryA(temporary, NULL)) return 0;
    if (strlen(temporary) + 1 > capacity) return 0;
    strcpy(path, temporary);
    return 1;
}
#else
static int create_temp_directory(char *path, size_t capacity) {
    const char *base = getenv("TMPDIR");
    if (base == NULL || base[0] == '\0') base = "/tmp";
    if (snprintf(path, capacity, "%s/pything-XXXXXX", base) >= (int)capacity) return 0;
    return mkdtemp(path) != NULL;
}
#endif

#ifndef _WIN32
static void remove_tree(const char *path) {
    DIR *directory = opendir(path);
    if (directory == NULL) {
        unlink(path);
        return;
    }
    struct dirent *entry;
    while ((entry = readdir(directory)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) continue;
        char child[PATH_CAPACITY];
        if (snprintf(child, sizeof(child), "%s/%s", path, entry->d_name) >= (int)sizeof(child)) continue;
        struct stat info;
        if (lstat(child, &info) == 0 && S_ISDIR(info.st_mode)) remove_tree(child);
        else unlink(child);
    }
    closedir(directory);
    rmdir(path);
}
#else
static void remove_tree(const char *path) {
    char pattern[PATH_CAPACITY];
    if (snprintf(pattern, sizeof(pattern), "%s\\*", path) >= (int)sizeof(pattern)) return;
    WIN32_FIND_DATAA data;
    HANDLE handle = FindFirstFileA(pattern, &data);
    if (handle != INVALID_HANDLE_VALUE) {
        do {
            if (strcmp(data.cFileName, ".") == 0 || strcmp(data.cFileName, "..") == 0) continue;
            char child[PATH_CAPACITY];
            if (snprintf(child, sizeof(child), "%s\\%s", path, data.cFileName) >= (int)sizeof(child)) continue;
            if (data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) remove_tree(child);
            else DeleteFileA(child);
        } while (FindNextFileA(handle, &data));
        FindClose(handle);
    }
    RemoveDirectoryA(path);
}
#endif

static const char *temporary_root = NULL;

#ifndef _WIN32
/* The pid of the child currently being waited on, so signals can be forwarded
   to its whole process group (uv plus every Python process below it). */
static volatile sig_atomic_t child_pid = 0;
static volatile sig_atomic_t signal_strikes = 0;
static volatile sig_atomic_t interrupted = 0;

static void forward_signal(int sig) {
    pid_t pid = (pid_t)child_pid;
    interrupted = 1;
    if (pid > 0) {
        if (kill(-pid, sig) != 0) kill(pid, sig);
        /* Escalate if the tree ignores repeated interrupts. */
        if (signal_strikes == 2) {
            kill(-pid, SIGTERM);
            kill(pid, SIGTERM);
        } else if (signal_strikes >= 3) {
            kill(-pid, SIGKILL);
            kill(pid, SIGKILL);
        }
    }
}
#else
static volatile HANDLE child_handle = NULL;
static volatile LONG cleanup_state = 0;

/* The child shares this console, so Ctrl+C reaches it on its own; this handler
   keeps the launcher alive just long enough to clean up and exit. */
static BOOL WINAPI console_ctrl_handler(DWORD event) {
    HANDLE handle = (HANDLE)child_handle;
    if (event == CTRL_C_EVENT) GenerateConsoleCtrlEvent(CTRL_C_EVENT, 0);
    if (handle != NULL) {
        if (WaitForSingleObject(handle, 10000) != WAIT_OBJECT_0) {
            TerminateProcess(handle, 1);
            WaitForSingleObject(handle, 5000);
        }
    }
    if (InterlockedCompareExchange(&cleanup_state, 1, 0) == 0) {
        if (temporary_root != NULL) remove_tree(temporary_root);
        InterlockedExchange(&cleanup_state, 2);
        ExitProcess(130);
    }
    return TRUE;
}
#endif

#ifdef _WIN32
static int append_command_argument(char *command, size_t capacity, size_t *used,
                                   const char *argument) {
    if (*used + 2 >= capacity) return 0;
    command[(*used)++] = '"';
    size_t slashes = 0;
    for (const char *p = argument; ; p++) {
        if (*p == '\\') {
            slashes++;
        } else if (*p == '"') {
            while (slashes-- > 0) {
                if (*used + 2 >= capacity) return 0;
                command[(*used)++] = '\\';
                command[(*used)++] = '\\';
            }
            slashes = 0;
            if (*used + 2 >= capacity) return 0;
            command[(*used)++] = '\\';
            command[(*used)++] = '"';
        } else if (*p == '\0') {
            while (slashes-- > 0) {
                if (*used + 2 >= capacity) return 0;
                command[(*used)++] = '\\';
                command[(*used)++] = '\\';
            }
            command[(*used)++] = '"';
            return 1;
        } else {
            while (slashes-- > 0) {
                if (*used + 1 >= capacity) return 0;
                command[(*used)++] = '\\';
            }
            slashes = 0;
            if (*used + 2 >= capacity) return 0;
            command[(*used)++] = *p;
        }
    }
}

static int run_capture(const char *const arguments[], char *output, size_t capacity) {
    SECURITY_ATTRIBUTES security = {sizeof(SECURITY_ATTRIBUTES), NULL, TRUE};
    HANDLE read_pipe = NULL, write_pipe = NULL;
    if (!CreatePipe(&read_pipe, &write_pipe, &security, 0)) return -1;
    SetHandleInformation(read_pipe, HANDLE_FLAG_INHERIT, 0);

    char command[PATH_CAPACITY];
    size_t used = 0;
    for (size_t i = 0; arguments[i] != NULL; i++) {
        if (i > 0) {
            if (used + 1 >= sizeof(command)) goto failed;
            command[used++] = ' ';
        }
        if (!append_command_argument(command, sizeof(command), &used, arguments[i])) goto failed;
    }
    command[used] = '\0';

    STARTUPINFOA startup;
    PROCESS_INFORMATION process;
    ZeroMemory(&startup, sizeof(startup));
    ZeroMemory(&process, sizeof(process));
    startup.cb = sizeof(startup);
    startup.dwFlags = STARTF_USESTDHANDLES;
    startup.hStdOutput = write_pipe;
    startup.hStdError = GetStdHandle(STD_ERROR_HANDLE);
    startup.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
    if (!CreateProcessA(arguments[0], command, NULL, NULL, TRUE, 0, NULL, NULL,
                        &startup, &process)) goto failed;
    child_handle = process.hProcess;
    CloseHandle(write_pipe);
    write_pipe = NULL;
    size_t used_output = 0;
    DWORD amount;
    char buffer[1024];
    while (ReadFile(read_pipe, buffer, sizeof(buffer), &amount, NULL) && amount > 0) {
        size_t copy = amount;
        if (copy > capacity - 1 - used_output) copy = capacity - 1 - used_output;
        if (copy > 0) {
            memcpy(output + used_output, buffer, copy);
            used_output += copy;
        }
    }
    output[used_output] = '\0';
    CloseHandle(read_pipe);
    WaitForSingleObject(process.hProcess, INFINITE);
    child_handle = NULL;
    DWORD exit_code = 1;
    GetExitCodeProcess(process.hProcess, &exit_code);
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return (int)exit_code;

failed:
    if (read_pipe) CloseHandle(read_pipe);
    if (write_pipe) CloseHandle(write_pipe);
    return -1;
}

static int run_process(const char *const arguments[]) {
    char command[PATH_CAPACITY];
    size_t used = 0;
    for (size_t i = 0; arguments[i] != NULL; i++) {
        if (i > 0) {
            if (used + 1 >= sizeof(command)) return -1;
            command[used++] = ' ';
        }
        if (!append_command_argument(command, sizeof(command), &used, arguments[i])) return -1;
    }
    command[used] = '\0';
    STARTUPINFOA startup;
    PROCESS_INFORMATION process;
    ZeroMemory(&startup, sizeof(startup));
    ZeroMemory(&process, sizeof(process));
    startup.cb = sizeof(startup);
    if (!CreateProcessA(arguments[0], command, NULL, NULL, FALSE, 0, NULL, NULL,
                        &startup, &process)) return -1;
    child_handle = process.hProcess;
    WaitForSingleObject(process.hProcess, INFINITE);
    child_handle = NULL;
    DWORD exit_code = 1;
    GetExitCodeProcess(process.hProcess, &exit_code);
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return (int)exit_code;
}
#else
static int run_capture(const char *const arguments[], char *output, size_t capacity) {
    if (interrupted) return -1;
    int pipes[2];
    if (pipe(pipes) != 0) return -1;
    pid_t child = fork();
    if (child == 0) {
        signal(SIGINT, SIG_DFL);
        signal(SIGTERM, SIG_DFL);
        signal(SIGHUP, SIG_DFL);
        setpgid(0, 0);
        close(pipes[0]);
        dup2(pipes[1], STDOUT_FILENO);
        close(pipes[1]);
        execv(arguments[0], (char *const *)arguments);
        _exit(127);
    }
    close(pipes[1]);
    if (child < 0) {
        close(pipes[0]);
        return -1;
    }
    child_pid = child;
    size_t used = 0;
    ssize_t amount;
    char buffer[1024];
    do {
        amount = read(pipes[0], buffer, sizeof(buffer));
    } while (amount < 0 && errno == EINTR);
    while (amount > 0) {
        size_t copy = (size_t)amount;
        if (copy > capacity - 1 - used) copy = capacity - 1 - used;
        if (copy > 0) {
            memcpy(output + used, buffer, copy);
            used += copy;
        }
        do {
            amount = read(pipes[0], buffer, sizeof(buffer));
        } while (amount < 0 && errno == EINTR);
    }
    output[used] = '\0';
    close(pipes[0]);
    int status = 0;
    pid_t waited;
    do {
        waited = waitpid(child, &status, 0);
    } while (waited < 0 && errno == EINTR);
    child_pid = 0;
    if (waited < 0) return -1;
    if (WIFEXITED(status)) return WEXITSTATUS(status);
    return 128;
}

static int run_process(const char *const arguments[]) {
    if (interrupted) return -1;
    pid_t child = fork();
    if (child == 0) {
        signal(SIGINT, SIG_DFL);
        signal(SIGTERM, SIG_DFL);
        signal(SIGHUP, SIG_DFL);
        setpgid(0, 0);
        execv(arguments[0], (char *const *)arguments);
        perror("Could not start subprocess");
        _exit(127);
    }
    if (child < 0) return -1;
    child_pid = child;
    int status = 0;
    pid_t waited;
    do {
        waited = waitpid(child, &status, 0);
    } while (waited < 0 && errno == EINTR);
    pid_t group = (pid_t)child_pid;
    child_pid = 0;
    if (waited < 0) return -1;
    /* uv may exit while slower grandchildren are still shutting down; give the
       rest of its process group a moment before the launcher tears down. */
    struct timespec pause = {0, 100 * 1000 * 1000};
    for (int attempt = 0; attempt < 50; attempt++) {
        if (kill(-group, 0) != 0) break;
        nanosleep(&pause, NULL);
        if (attempt == 19) kill(-group, SIGTERM);
        if (attempt == 39) kill(-group, SIGKILL);
    }
    if (WIFEXITED(status)) return WEXITSTATUS(status);
    if (WIFSIGNALED(status)) return 128 + WTERMSIG(status);
    return 1;
}
#endif

static int set_runtime_environment(const char *name, const char *value) {
#ifdef _WIN32
    return _putenv_s(name, value) == 0;
#else
    return setenv(name, value, 1) == 0;
#endif
}

static int make_directory_path(const char *path) {
    char copy[PATH_CAPACITY];
    if (strlen(path) + 1 > sizeof(copy)) return 0;
    strcpy(copy, path);
#ifdef _WIN32
    char *start = copy + (strlen(copy) > 2 && copy[1] == ':' ? 3 : (copy[0] == '\\' ? 1 : 0));
#else
    char *start = copy + (copy[0] == '/' ? 1 : 0);
#endif
    for (char *p = start; *p; p++) {
        if (*p == '/' || *p == '\\') {
            char separator = *p;
            *p = '\0';
#ifdef _WIN32
            if (!CreateDirectoryA(copy, NULL) && GetLastError() != ERROR_ALREADY_EXISTS) return 0;
#else
            if (mkdir(copy, 0755) != 0 && errno != EEXIST) return 0;
#endif
            *p = separator;
        }
    }
#ifdef _WIN32
    return CreateDirectoryA(copy, NULL) || GetLastError() == ERROR_ALREADY_EXISTS;
#else
    return mkdir(copy, 0755) == 0 || errno == EEXIST;
#endif
}

static int get_dependency_target(const char *python_path, char *target, size_t capacity) {
    static const char code[] =
        "import os,sys,sysconfig; "
        "root=(os.environ.get('LOCALAPPDATA') if sys.platform=='win32' else "
        "(os.path.join(os.path.expanduser('~'),'Library','Caches') if sys.platform=='darwin' "
        "else (os.environ.get('XDG_CACHE_HOME') or os.path.join(os.path.expanduser('~'),'.cache')))); "
        "print(os.path.join(root,'pything','dependencies'," 
        "f'{sys.implementation.cache_tag}-{sysconfig.get_platform()}'))";
    const char *arguments[] = {python_path, "-c", code, NULL};
    int result = run_capture(arguments, target, capacity);
    if (result != 0) return 0;
    size_t length = strlen(target);
    while (length > 0 && (target[length - 1] == '\n' || target[length - 1] == '\r'))
        target[--length] = '\0';
    return length > 0;
}

static int detect_python(const char *uv_path, const char *version,
                         char *python_path, size_t capacity) {
    const char *find_arguments[] = {uv_path, "python", "find", "--system", "--no-project",
                                    "--no-python-downloads", version, NULL};
    if (run_capture(find_arguments, python_path, capacity) == 0) {
        size_t length = strlen(python_path);
        while (length > 0 && (python_path[length - 1] == '\n' || python_path[length - 1] == '\r'))
            python_path[--length] = '\0';
        if (length > 0) return 1;
    }

    char venv_path[PATH_CAPACITY];
#ifdef _WIN32
    const char *base = getenv("LOCALAPPDATA");
    if (base == NULL || base[0] == '\0') base = getenv("TEMP");
    if (base == NULL || snprintf(venv_path, sizeof(venv_path), "%s\\pything\\venv", base) >= (int)sizeof(venv_path))
        return 0;
    const char *python_in_venv = "Scripts\\python.exe";
#else
    const char *base = getenv("XDG_CACHE_HOME");
    if (base == NULL || base[0] == '\0') {
        base = getenv("HOME");
        if (base == NULL || base[0] == '\0') {
            struct passwd *user = getpwuid(getuid());
            base = user != NULL ? user->pw_dir : "/tmp";
        }
        if (snprintf(venv_path, sizeof(venv_path), "%s/.cache/pything/venv", base) >= (int)sizeof(venv_path))
            return 0;
    } else if (snprintf(venv_path, sizeof(venv_path), "%s/pything/venv", base) >= (int)sizeof(venv_path)) {
        return 0;
    }
    const char *python_in_venv = "bin/python";
#endif
    const char *venv_arguments[] = {uv_path, "venv", "--python", version, "--allow-existing", venv_path, NULL};
    if (run_process(venv_arguments) != 0) return 0;
#ifdef _WIN32
    return snprintf(python_path, capacity, "%s\\%s", venv_path, python_in_venv) < (int)capacity;
#else
    return snprintf(python_path, capacity, "%s/%s", venv_path, python_in_venv) < (int)capacity;
#endif
}

static int install_runtime_dependencies(const char *uv_path, const char *python_path,
                                        const char *target) {
    if (!make_directory_path(target)) {
        fprintf(stderr, "Could not create dependency directory: %s\n", target);
        return 0;
    }
    const char *arguments[] = {uv_path, "pip", "install", "--python", python_path,
                               "--target", target, "flask==3.1.2",
                               "flask-socketio==5.5.1", "packaging>=24.0",
                               "truststore>=0.10.4", NULL};
    return run_process(arguments) == 0;
}

static int configure_pythonpath(const char *source_directory, const char *dependency_directory) {
    const char *existing = getenv("PYTHONPATH");
    if (existing == NULL) existing = "";
    char pythonpath[PATH_CAPACITY * 2];
#ifdef _WIN32
    const char separator = ';';
#else
    const char separator = ':';
#endif
    int length;
    if (existing[0] == '\0')
        length = snprintf(pythonpath, sizeof(pythonpath), "%s%c%s", source_directory, separator, dependency_directory);
    else
        length = snprintf(pythonpath, sizeof(pythonpath), "%s%c%s%c%s", source_directory, separator,
                          dependency_directory, separator, existing);
    return length >= 0 && (size_t)length < sizeof(pythonpath) &&
           set_runtime_environment("PYTHONPATH", pythonpath);
}

static int run_package(void) {
    char temporary[PATH_CAPACITY];
    if (!create_temp_directory(temporary, sizeof(temporary))) {
        fprintf(stderr, "Could not create a temporary directory.\n");
        return 1;
    }
    temporary_root = temporary;
#ifndef _WIN32
    struct sigaction action;
    memset(&action, 0, sizeof(action));
    action.sa_handler = forward_signal;
    action.sa_flags = SA_RESTART;
    sigaction(SIGINT, &action, NULL);
    sigaction(SIGTERM, &action, NULL);
    sigaction(SIGHUP, &action, NULL);
#else
    SetConsoleCtrlHandler(console_ctrl_handler, TRUE);
#endif
    const char *dev = getenv("DEV");
    if (dev != NULL && strcmp(dev, "true") == 0) {
        printf("Extraction directory: %s\n", temporary);
        fflush(stdout);
    }
#ifdef _WIN32
    char executable_path[PATH_CAPACITY];
    DWORD executable_length = GetModuleFileNameA(NULL, executable_path, (DWORD)sizeof(executable_path));
    FILE *self = executable_length > 0 && executable_length < sizeof(executable_path)
                     ? fopen(executable_path, "rb")
                     : NULL;
#else
    FILE *self = fopen("/proc/self/exe", "rb");
#endif
    if (self == NULL) {
        fprintf(stderr, "Could not open launcher executable.\n");
        remove_tree(temporary);
        return 1;
    }
    uint64_t total_size;
    if (!file_size(self, &total_size) || !extract_archive(self, total_size, temporary)) {
        fprintf(stderr, "Could not extract the packaged PYThing files.\n");
        fclose(self);
        remove_tree(temporary);
        return 1;
    }
    fclose(self);
#ifndef _WIN32
    if (interrupted) goto cleanup;
#endif

#ifdef _WIN32
    char original_directory[PATH_CAPACITY];
    if (_getcwd(original_directory, sizeof(original_directory)) == NULL) original_directory[0] = '\0';
    char uv_path[PATH_CAPACITY];
    const char *python_version = "3.12";
    if (!join_path(uv_path, sizeof(uv_path), temporary, "bin/uv.exe")) {
        remove_tree(temporary);
        return 1;
    }
    if (_chdir(temporary) != 0) {
        fprintf(stderr, "Could not enter the temporary project directory.\n");
        remove_tree(temporary);
        return 1;
    }
#else
    char uv_path[PATH_CAPACITY];
    const char *python_version = "3.14";
    if (!join_path(uv_path, sizeof(uv_path), temporary, "bin/uv")) {
        remove_tree(temporary);
        return 1;
    }
    if (chdir(temporary) != 0) {
        perror("Could not enter the temporary project directory");
        remove_tree(temporary);
        return 1;
    }
#endif

    char python_path[PATH_CAPACITY];
    char dependency_directory[PATH_CAPACITY];
    char source_directory[PATH_CAPACITY];
    int result = 1;
    if (!detect_python(uv_path, python_version, python_path, sizeof(python_path))) {
        fprintf(stderr, "Could not find or create Python %s.\n", python_version);
        goto cleanup;
    }
    if (dev != NULL && strcmp(dev, "true") == 0) {
        printf("Python executable: %s\n", python_path);
        fflush(stdout);
    }
    if (!get_dependency_target(python_path, dependency_directory, sizeof(dependency_directory))) {
        fprintf(stderr, "Could not determine the PYThing dependency directory.\n");
        goto cleanup;
    }
    if (!install_runtime_dependencies(uv_path, python_path, dependency_directory)) {
        fprintf(stderr, "Could not install PYThing runtime dependencies.\n");
        goto cleanup;
    }
    if (!join_path(source_directory, sizeof(source_directory), temporary, "src") ||
        !configure_pythonpath(source_directory, dependency_directory) ||
        !set_runtime_environment("PYTHING_SERVER_MODE", "1") ||
        !set_runtime_environment("PYTHING_PYTHON", python_path) ||
        !set_runtime_environment("PYTHING_UV", uv_path)) {
        fprintf(stderr, "Could not configure PYThing's runtime environment.\n");
        goto cleanup;
    }
#ifndef _WIN32
    if (interrupted) goto cleanup;
#endif
    {
        const char *arguments[] = {uv_path, "run", "--no-project", "--python", python_path,
                                   "-m", "pything", NULL};
        result = run_process(arguments);
        if (result < 0) {
            fprintf(stderr, "Could not start PYThing with uv.\n");
            result = 1;
        }
    }
cleanup:
#ifdef _WIN32
    if (original_directory[0] != '\0')
        _chdir(original_directory);
    else {
        char temp_base[PATH_CAPACITY];
        DWORD length = GetTempPathA((DWORD)sizeof(temp_base), temp_base);
        if (length > 0 && length < sizeof(temp_base)) _chdir(temp_base);
    }
#else
    chdir("/");
#endif
#ifdef _WIN32
    if (InterlockedCompareExchange(&cleanup_state, 1, 0) == 0) {
        remove_tree(temporary);
        InterlockedExchange(&cleanup_state, 2);
    }
#else
    child_pid = 0;
    remove_tree(temporary);
#endif
    return result;
}

int main(int argc, char **argv) {
    if (argc == 4 && strcmp(argv[1], "--pack") == 0)
        return make_package(argv[0], argv[2], argv[3]);
    return run_package();
}
