import enum


class Role(str, enum.Enum):
    REPORTER = "reporter"        # 报案人
    SURVEYOR = "surveyor"        # 查勘员
    ADJUSTER = "adjuster"        # 理算员
    PAY_OFFICER = "pay_officer"  # 付款复核员


class ItemStatus(str, enum.Enum):
    SUBMITTED = "submitted"          # 已上传，待查勘
    RECOGNIZED = "recognized"        # 查勘认可（认可金额确定）
    DISPUTED = "disputed"            # 有争议，待补证/报价
    RECOGNIZED_AFTER_DISPUTE = "recognized_after_dispute"  # 争议后补证获认可


class MaterialStatus(str, enum.Enum):
    PENDING = "pending"        # 待补证
    SUBMITTED = "submitted"    # 已补交，待审核
    ACCEPTED = "accepted"      # 审核通过
    REJECTED = "rejected"      # 审核不通过


class OfferStatus(str, enum.Enum):
    OPEN = "open"              # 待报案人接受
    ACCEPTED = "accepted"      # 已接受
    REJECTED = "rejected"      # 已拒绝
    CONFLICTED = "conflicted"  # 接受期间认可金额变化，报价冲突失效


class BatchStatus(str, enum.Enum):
    PENDING_ACCEPTANCE = "pending_acceptance"  # 待报案人接受
    ACCEPTED = "accepted"                      # 已接受，待付款
    PAID = "paid"                              # 全部款项支付成功
    CANCELLED = "cancelled"                    # 作废（冲突后重建）


class PaymentStatus(str, enum.Enum):
    LOCKED = "locked"                  # 已锁定待支付（占用事故额度）
    SUBMITTED_UNKNOWN = "submitted_unknown"  # 已提交，结果未知（回执丢失）
    SUCCEEDED = "succeeded"            # 支付成功
    DECLINED = "declined"              # 明确拒绝
    TIMED_OUT = "timed_out"            # 提交超时（结果未知，不重新生成付款）


class CorrectionStatus(str, enum.Enum):
    OPEN = "open"          # 待人工处理
    PROCESSED = "processed"  # 已处理


class GatewayOutcome(str, enum.Enum):
    SUCCESS = "success"                # 成功并即时返回回执
    SUCCESS_RECEIPT_LOST = "success_receipt_lost"  # 成功但响应丢失
    LATE_SUCCESS = "late_success"      # 首次结果未知，稍后查询成功
    DECLINE = "decline"                # 明确拒绝
