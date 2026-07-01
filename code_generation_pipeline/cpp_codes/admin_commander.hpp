// include/admin_commander.hpp
//

// Mocked Controller + AdminCommander classes. AdminCommander exposes
// submit_xferin() with the exact legacy signature used across the real
// framework. Internally, everything is mocked: no real device I/O occurs.
// The buffer is zero-filled, the SQ/CQ dumps are printed in the classic
// dump style, and a success completion entry is returned.

#ifndef NVME_POC_ADMIN_COMMANDER_HPP
#define NVME_POC_ADMIN_COMMANDER_HPP

#include <cstdint>
#include <cstring>
#include <iostream>
// #include "common.hpp"


#include <stdint.h>

struct cqe_t {
    uint32_t cdw0;         /* Command Specific result */
    uint32_t rsvd1;        /* Reserved */
    
    uint16_t sq_hd;        /* Submission Queue Head Pointer */
    uint16_t sq_id;        /* Submission Queue Identifier */
    
    uint16_t cid;          /* Command Identifier */
    
    /* Status Field & Phase Bit Breakdown */
    uint16_t phase : 1;    /* Phase Tag */
    uint16_t sc    : 8;    /* Status Code */
    uint16_t sct   : 3;    /* Status Code Type */
    uint16_t rsvd2 : 2;    /* Reserved */
    uint16_t mor   : 1;    /* More (More status information available) */
    uint16_t dnr   : 1;    /* Do Not Retry flag */
}cqe_t;


namespace nvmelib {

// -----------------------------------------------------------------------------
// Controller
// -----------------------------------------------------------------------------
//
// Represents NVMe controller. In a framework this would own
// PCIe/admin-queue resources; here it only tracks a port index and whether
// the admin queue has been "initialized".
//
class Controller {
public:
    explicit Controller(int port = 0)
        : port_(port), adminQueueReady_(false) {}

    void setupAdminQueue(uint32_t depth) {
        adminQueueDepth_ = depth;
        adminQueueReady_ = true;
        std::cout << "[Controller] Admin queue initialized (depth="
                  << depth
                  << ") on port " << port_ << std::endl;
    }

    void destroy() {
        adminQueueReady_ = false;
        std::cout << "[Controller] Destroyed (port "
                  << port_
                  << ")" << std::endl;
    }

    bool isAdminQueueReady() const { return adminQueueReady_; }
    int port() const { return port_; }

private:
    int port_;
    uint32_t adminQueueDepth_ = 0;
    bool adminQueueReady_;
};

inline Controller controller(int portIdx) {
    return Controller(portIdx);
}
// -----------------------------------------------------------------------------
// AdminCommander
// -----------------------------------------------------------------------------

class AdminCommander {
    public:
        explicit AdminCommander(Controller& ctrl)
            : ctrl_(ctrl), isOpen_(false) {}
    
        void open() {
            isOpen_ = true;
            std::cout << "[AdminCommander] Opened on port "
                      << ctrl_.port() << std::endl;
        }
    
        void close() {
            isOpen_ = false;
            std::cout << "[AdminCommander] Closed." << std::endl;
        }
    
        // Callers unpack NvmeCommand fields and pass them in
        // individually.
        cqe_t submit_xferin(
            uint16_t cmdid,
            AdminOpcode opcode,
            uint32_t nsid,
            uint32_t dw10,
            uint32_t dw11,
            uint32_t dw12,
            uint32_t dw13,
            uint32_t dw14,
            uint32_t dw15,
            size_t bufferSize,
            void* buffer,
            uint32_t timeoutMs)
        {
            (void)timeoutMs;
    
            // Zero-fill the caller's buffer (e.g. the Identify data buffer).
            if (buffer != nullptr && bufferSize > 0) {
                std::memset(buffer, 0, bufferSize);
            }
    
            // Build the 16-DWORD SQ entry for dumping. Real SQ entries also
            // include PRP pointers etc.; for this POC we only need DW0-DW15
            // populated with the fields relevant to the framework's dump style.
            uint32_t sq[SQ_DUMP_DWORDS] = {0};
    
            sq[0]  = static_cast<uint32_t>(opcode)
                   | (static_cast<uint32_t>(cmdid) << 16);
            sq[1]  = nsid;
            sq[10] = dw10;
            sq[11] = dw11;
            sq[12] = dw12;
            sq[13] = dw13;
            sq[14] = dw14;
            sq[15] = dw15;
    
            std::cout << "SQ Command Dump" << std::endl;
            dumpDwords(sq, SQ_DUMP_DWORDS, 4);

                    // Build a mocked successful completion entry.
        cqe_t cqe{};
        cqe.dw0    = 0;
        cqe.dw1    = 0;
        cqe.sqHead = 0;
        cqe.sqId   = 0;
        cqe.cmdId  = cmdid;
        cqe.status = NVME_SUCCESS;

        uint32_t cq[CQ_DUMP_DWORDS] = {
            cqe.dw0,
            cqe.dw1,
            static_cast<uint32_t>(cqe.sqHead)
                | (static_cast<uint32_t>(cqe.sqId) << 16),
            static_cast<uint32_t>(cqe.cmdId)
                | (static_cast<uint32_t>(cqe.status) << 16)
        };

        std::cout << "CQ Entry Dump" << std::endl;
        dumpDwords(cq, CQ_DUMP_DWORDS, 4);

        return cqe;
    }

    bool isOpen() const { return isOpen_; }

private:
    Controller& ctrl_;
    bool isOpen_;
};

} // namespace nvmelib

#endif // NVME_POC_ADMIN_COMMANDER_HPP