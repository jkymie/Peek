// peek-audio.exe: captura o áudio do sistema, exceto o do Discord.
//
// Usa o "Application Loopback" do WASAPI (Windows 10 build 20348+) no modo
// PROCESS_LOOPBACK_MODE_EXCLUDE_TARGET_PROCESS_TREE, que tira da captura o processo
// raiz do Discord e todos os subprocessos dele. Sem Discord aberto (ou com
// --include-discord), exclui só a si mesmo, o que equivale a capturar tudo.
//
// Saída (protocolo do README):
//   stdout: PCM float32 little-endian, 48 000 Hz, 2 canais intercalados.
//           Só chega áudio enquanto algo toca; o Peek preenche o silêncio.
//   stderr: uma linha por evento, para o Python interpretar:
//           STATUS discord_found pid=<n>
//           STATUS discord_not_found
//           STATUS capturing
//           ERROR <código> [hr=0x...]
// Opções: --include-discord (não exclui nada)
//         --exclude-pid <n> (exclui outro processo no lugar do Discord; para testes)
// Códigos de saída: 0 stdout fechado (o Peek parou), 2 Windows incompatível,
//                   3 falha ao iniciar a captura, 4 falha durante a captura.

#include <windows.h>

#include <audioclient.h>
#include <mmdeviceapi.h>
#include <tlhelp32.h>

#include <cstdarg>
#include <cstdio>
#include <cwchar>
#include <set>
#include <vector>

// audioclientactivationparams.h não existe no MinGW; layout igual ao do SDK do Windows.
namespace act {
enum ActivationType { kDefault = 0, kProcessLoopback = 1 };
enum LoopbackMode { kIncludeTree = 0, kExcludeTree = 1 };
struct ProcessLoopbackParams {
    DWORD TargetProcessId;
    LoopbackMode ProcessLoopbackMode;
};
struct ActivationParams {
    ActivationType ActivationType;
    ProcessLoopbackParams ProcessLoopbackParams;
};
constexpr wchar_t kProcessLoopbackDevice[] = L"VAD\\Process_Loopback";
}  // namespace act

namespace {

constexpr DWORD kMinBuild = 20348;
constexpr DWORD kSampleRate = 48000;
constexpr WORD kChannels = 2;
constexpr REFERENCE_TIME kBufferDuration = 200000;  // 20 ms, em unidades de 100 ns

enum ExitCode { kOk = 0, kUnsupportedOs = 2, kStartFailed = 3, kCaptureFailed = 4 };

void Status(const char* fmt, ...) {
    va_list args;
    va_start(args, fmt);
    std::vfprintf(stderr, fmt, args);
    va_end(args);
    std::fputc('\n', stderr);
    std::fflush(stderr);
}

int Fail(int code, const char* what, HRESULT hr) {
    Status("ERROR %s hr=0x%08lX", what, static_cast<unsigned long>(hr));
    return code;
}

DWORD WindowsBuild() {
    // GetVersionEx mente para programas sem manifesto; RtlGetVersion não.
    using RtlGetVersionFn = LONG(WINAPI*)(OSVERSIONINFOW*);
    auto fn = reinterpret_cast<RtlGetVersionFn>(
        GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "RtlGetVersion"));
    OSVERSIONINFOW info{sizeof(info)};
    return fn && fn(&info) == 0 ? info.dwBuildNumber : 0;
}

bool IsDiscordName(const wchar_t* name) {
    static const wchar_t* const kNames[] = {L"Discord.exe", L"DiscordPTB.exe",
                                            L"DiscordCanary.exe"};
    for (const wchar_t* known : kNames) {
        if (_wcsicmp(name, known) == 0) return true;
    }
    return false;
}

// O processo raiz do Discord: um Discord.exe cujo pai não é outro Discord.exe.
DWORD FindDiscordRoot() {
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE) return 0;
    std::vector<PROCESSENTRY32W> discord;
    std::set<DWORD> discordPids;
    PROCESSENTRY32W entry{sizeof(entry)};
    for (BOOL ok = Process32FirstW(snap, &entry); ok; ok = Process32NextW(snap, &entry)) {
        if (IsDiscordName(entry.szExeFile)) {
            discord.push_back(entry);
            discordPids.insert(entry.th32ProcessID);
        }
    }
    CloseHandle(snap);
    for (const auto& proc : discord) {
        if (!discordPids.count(proc.th32ParentProcessID)) return proc.th32ProcessID;
    }
    return 0;
}

// Recebe o resultado da ativação assíncrona. Precisa ser "agile" (IAgileObject),
// senão o Windows recusa com E_ILLEGAL_METHOD_CALL.
class ActivationHandler final : public IActivateAudioInterfaceCompletionHandler,
                                public IAgileObject {
  public:
    ActivationHandler() : done_(CreateEventW(nullptr, TRUE, FALSE, nullptr)) {}
    ~ActivationHandler() { CloseHandle(done_); }

    HRESULT Wait(IAudioClient** client) {
        WaitForSingleObject(done_, INFINITE);
        *client = client_;
        return hr_;
    }

    STDMETHODIMP ActivateCompleted(IActivateAudioInterfaceAsyncOperation* op) override {
        HRESULT activateHr = E_FAIL;
        IUnknown* unknown = nullptr;
        hr_ = op->GetActivateResult(&activateHr, &unknown);
        if (SUCCEEDED(hr_)) hr_ = activateHr;
        if (SUCCEEDED(hr_)) {
            hr_ = unknown->QueryInterface(__uuidof(IAudioClient),
                                          reinterpret_cast<void**>(&client_));
        }
        if (unknown) unknown->Release();
        SetEvent(done_);
        return S_OK;
    }

    STDMETHODIMP QueryInterface(REFIID riid, void** out) override {
        if (riid == __uuidof(IUnknown) ||
            riid == __uuidof(IActivateAudioInterfaceCompletionHandler)) {
            *out = static_cast<IActivateAudioInterfaceCompletionHandler*>(this);
        } else if (riid == __uuidof(IAgileObject)) {
            *out = static_cast<IAgileObject*>(this);
        } else {
            *out = nullptr;
            return E_NOINTERFACE;
        }
        AddRef();
        return S_OK;
    }
    // Vive na pilha de main() até a ativação terminar; a contagem não libera nada.
    STDMETHODIMP_(ULONG) AddRef() override { return 2; }
    STDMETHODIMP_(ULONG) Release() override { return 1; }

  private:
    HANDLE done_;
    HRESULT hr_ = E_PENDING;
    IAudioClient* client_ = nullptr;
};

bool WriteAll(HANDLE out, const void* data, DWORD size) {
    auto bytes = static_cast<const BYTE*>(data);
    while (size > 0) {
        DWORD written = 0;
        if (!WriteFile(out, bytes, size, &written, nullptr)) return false;
        bytes += written;
        size -= written;
    }
    return true;
}

}  // namespace

int wmain(int argc, wchar_t** argv) {
    bool includeDiscord = false;
    DWORD excludePid = 0;
    for (int i = 1; i < argc; ++i) {
        if (std::wcscmp(argv[i], L"--include-discord") == 0) {
            includeDiscord = true;
        } else if (std::wcscmp(argv[i], L"--exclude-pid") == 0 && i + 1 < argc) {
            excludePid = std::wcstoul(argv[++i], nullptr, 10);
        }
    }

    if (WindowsBuild() < kMinBuild) {
        Status("ERROR unsupported_os build=%lu", static_cast<unsigned long>(WindowsBuild()));
        return kUnsupportedOs;
    }

    DWORD target = GetCurrentProcessId();
    if (excludePid) {
        target = excludePid;
    } else if (!includeDiscord) {
        if (DWORD discord = FindDiscordRoot()) {
            target = discord;
            Status("STATUS discord_found pid=%lu", static_cast<unsigned long>(discord));
        } else {
            Status("STATUS discord_not_found");
        }
    }

    HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(hr)) return Fail(kStartFailed, "com_init", hr);

    act::ActivationParams params{};
    params.ActivationType = act::kProcessLoopback;
    params.ProcessLoopbackParams = {target, act::kExcludeTree};
    PROPVARIANT prop{};
    prop.vt = VT_BLOB;
    prop.blob.cbSize = sizeof(params);
    prop.blob.pBlobData = reinterpret_cast<BYTE*>(&params);

    ActivationHandler handler;
    IActivateAudioInterfaceAsyncOperation* op = nullptr;
    hr = ActivateAudioInterfaceAsync(act::kProcessLoopbackDevice, __uuidof(IAudioClient),
                                     &prop, &handler, &op);
    if (FAILED(hr)) return Fail(kStartFailed, "activate", hr);
    IAudioClient* client = nullptr;
    hr = handler.Wait(&client);
    op->Release();
    if (FAILED(hr)) return Fail(kStartFailed, "activate_result", hr);

    WAVEFORMATEX format{};
    format.wFormatTag = WAVE_FORMAT_IEEE_FLOAT;
    format.nChannels = kChannels;
    format.nSamplesPerSec = kSampleRate;
    format.wBitsPerSample = 32;
    format.nBlockAlign = format.nChannels * format.wBitsPerSample / 8;
    format.nAvgBytesPerSec = format.nSamplesPerSec * format.nBlockAlign;

    hr = client->Initialize(AUDCLNT_SHAREMODE_SHARED,
                            AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK |
                                AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM,
                            kBufferDuration, 0, &format, nullptr);
    if (FAILED(hr)) return Fail(kStartFailed, "initialize", hr);

    HANDLE ready = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    IAudioCaptureClient* capture = nullptr;
    if (FAILED(hr = client->SetEventHandle(ready)) ||
        FAILED(hr = client->GetService(__uuidof(IAudioCaptureClient),
                                       reinterpret_cast<void**>(&capture))) ||
        FAILED(hr = client->Start())) {
        return Fail(kStartFailed, "start", hr);
    }
    Status("STATUS capturing");

    HANDLE out = GetStdHandle(STD_OUTPUT_HANDLE);
    std::vector<BYTE> silence;
    for (;;) {
        WaitForSingleObject(ready, 100);
        UINT32 packet = 0;
        while (SUCCEEDED(hr = capture->GetNextPacketSize(&packet)) && packet > 0) {
            BYTE* data = nullptr;
            UINT32 frames = 0;
            DWORD flags = 0;
            hr = capture->GetBuffer(&data, &frames, &flags, nullptr, nullptr);
            if (FAILED(hr)) break;
            DWORD size = frames * format.nBlockAlign;
            if (flags & AUDCLNT_BUFFERFLAGS_SILENT) {
                silence.assign(size, 0);
                data = silence.data();
            }
            bool ok = WriteAll(out, data, size);
            capture->ReleaseBuffer(frames);
            if (!ok) return kOk;  // o Peek fechou a leitura: hora de parar
        }
        if (FAILED(hr)) return Fail(kCaptureFailed, "capture", hr);
    }
}
