"""虚构支付网关模拟器（不依赖真实银行接口）。

支持四种结果模式：
- success：提交即成功并返回回执；
- success_receipt_lost：扣款成功但响应丢失，首次提交结果未知，之后查询可得成功回执；
- late_success：首次提交与第一次查询均为处理中/未知，稍后再次查询才成功；
- decline：明确拒绝。

提交超时（timed_out）同样不代表失败：网关侧已生成交易号，只能凭交易号查询，
不得重新生成另一笔付款。模拟器状态保存在进程内存中，带锁保证并发安全。
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field

from ..enums import GatewayOutcome, PaymentStatus


class GatewayError(Exception):
    """提交阶段网络异常（如超时、响应丢失），交易结果未知。"""


class ReceiptLost(GatewayError):
    """网关已受理且扣款成功，但响应在途中丢失。"""


class SubmitTimeout(GatewayError):
    """提交超时：不知道网关是否受理，只能稍后查询。"""


@dataclass
class GatewayTxn:
    ref: str
    amount: str
    outcome: GatewayOutcome
    poll_count: int = 0
    finalized: bool = False  # 网关侧是否已形成最终结果
    accepted: bool = False   # 网关是否已受理（超时场景下可能已受理）
    history: list[str] = field(default_factory=list)


class _MockGateway:
    def __init__(self) -> None:
        self._txns: dict[str, GatewayTxn] = {}
        self._lock = threading.Lock()

    def new_ref(self) -> str:
        return "PAY-" + uuid.uuid4().hex[:16].upper()

    def submit(self, ref: str, amount: str, outcome: GatewayOutcome) -> GatewayTxn:
        with self._lock:
            txn = GatewayTxn(ref=ref, amount=amount, outcome=outcome)
            self._txns[ref] = txn
            txn.history.append("submit")
            if outcome == GatewayOutcome.SUCCESS:
                txn.finalized = True
                txn.accepted = True
                txn.history.append("approved")
                return txn
            if outcome == GatewayOutcome.DECLINE:
                txn.finalized = True
                txn.accepted = False
                txn.history.append("declined")
                return txn
            if outcome == GatewayOutcome.SUCCESS_RECEIPT_LOST:
                # 钱已扣、回执丢失
                txn.finalized = True
                txn.accepted = True
                txn.history.append("approved_but_response_lost")
                raise ReceiptLost(f"交易 {ref} 已成功但响应丢失")
            if outcome == GatewayOutcome.LATE_SUCCESS:
                txn.accepted = True
                txn.history.append("processing")
                raise SubmitTimeout(f"交易 {ref} 提交后超时，结果未知")
            raise ValueError(f"未知网关模式: {outcome}")

    def query(self, ref: str) -> PaymentStatus:
        """查询回执。返回 SUCCEEDED / DECLINED / SUBMITTED_UNKNOWN。"""
        with self._lock:
            txn = self._txns.get(ref)
            if txn is None:
                raise KeyError(ref)
            txn.poll_count += 1
            if txn.finalized:
                txn.history.append(f"poll#{txn.poll_count}:final")
                return PaymentStatus.SUCCEEDED if txn.accepted else PaymentStatus.DECLINED
            # LATE_SUCCESS：第二次查询时网关才出最终结果
            if txn.outcome == GatewayOutcome.LATE_SUCCESS and txn.poll_count >= 2:
                txn.finalized = True
                txn.accepted = True
                txn.history.append(f"poll#{txn.poll_count}:approved")
                return PaymentStatus.SUCCEEDED
            txn.history.append(f"poll#{txn.poll_count}:processing")
            return PaymentStatus.SUBMITTED_UNKNOWN

    def peek(self, ref: str) -> GatewayTxn | None:
        with self._lock:
            return self._txns.get(ref)

    def reset(self) -> None:
        with self._lock:
            self._txns.clear()


gateway = _MockGateway()
