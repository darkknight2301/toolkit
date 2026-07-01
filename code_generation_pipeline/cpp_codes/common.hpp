#include <cstdint>
#include <algorithm>
#include <ostream>

namespace nvmeLib {

// Mocked admin command timeout (milliseconds).
// In a real framework this
// would be tunable. A single generic timeout is fine.
constexpr uint32_t ADMIN_CMD_TIMEOUT = 30000;

// NSID used when a command is not namespace-specific
// (e.g. Identify Controller).
constexpr uint32_t DEFAULT_NSID = 0xFFFFFFFFu;

// Number of DWORDS printed when dumping an SQ command entry.
constexpr int SQ_DUMP_DWORDS = 16;

// Number of DWORDS printed when dumping a CQ entry.
constexpr int CQ_DUMP_DWORDS = 4;

// NVMe Admin Command opcodes (subset relevant to this POC; extend as needed)
enum class AdminOpcode : uint8_t {
    DeleteSQ       = 0x00,
    CreateSQ       = 0x01,
    GetLogPage     = 0x02,
    DeleteCQ       = 0x04,
    CreateCQ       = 0x05,
    Identify       = 0x06,
    Abort          = 0x08,
    SetFeatures    = 0x09,
    GetFeatures    = 0x0A,
    AsyncEventReq  = 0x0C,
    FirmwareDownload = 0x10,
    FirmwareCommit   = 0x11,
    FormatNvm        = 0x80,
};

// NVMe completion status codes (mocked subset)
constexpr uint16_t NVME_SUCCESS = 0x0000;

struct Cqe {
    uint32_t dw0;
    uint32_t dw1;
    uint16_t sqHd;
    uint16_t sqId;
    uint16_t cmdId;
    uint16_t status;
};

// Returns true if the completion entry indicates success.
inline bool isSuccess(const Cqe& cqe) {
    return cqe.status == NVME_SUCCESS;
}

// Prints a buffer of DWORDS in the classic "SQ/CQ Dump" hex format,
// e.g.
// 00000006 00000000 00000000 00000000
// 00000000 00000000 00000000 00000000
inline void dumpDwords(const uint32_t* dwords, int count, int perLine = 4) {
    for (int i = 0; i < count; ++i) {
        std::cout << std::hex << std::setw(8) << std::setfill('0')
                  << dwords[i] << " ";
        if ((i + 1) % perLine == 0) {
            std::cout << std::endl;
        }
    }
    std::cout << std::dec << std::endl;
}

} // namespace nvmeLib

#endif // NVME_POC_COMMON_HPP