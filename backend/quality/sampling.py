"""Chọn mẫu cho QC2 Audit.

Tách ra file riêng vì đây là logic thuần (không cần DB), dễ test và dễ đổi quy tắc
khi nhóm chốt cách sampling. Quy tắc dưới đây là ĐỀ XUẤT:

- Số mẫu = làm tròn LÊN (tỉ lệ % × số job), tối thiểu 1 nếu có job đủ điều kiện.
- Random: chọn ngẫu nhiên trên toàn bộ.
- Stratified: chia nhóm (tầng) theo một thuộc tính (vd. annotator), mỗi tầng lấy
  cùng tỉ lệ (làm tròn lên) → annotator nào cũng có job được kiểm.
- Dùng seed cố định để kết quả tái lập được và lưu được vào lịch sử.
"""

import math
import random
from collections import defaultdict


def sample_size(total, rate):
    if total <= 0:
        return 0
    return min(total, max(1, math.ceil(total * rate / 100)))


def random_sample(items, rate, seed):
    rng = random.Random(seed)
    return [(item, "") for item in rng.sample(list(items), sample_size(len(items), rate))]


def stratified_sample(items, rate, seed, key):
    """key(item) → tên tầng. Trả về [(item, tên tầng)]."""
    rng = random.Random(seed)
    strata = defaultdict(list)
    for item in items:
        strata[key(item)].append(item)
    picked = []
    for stratum in sorted(strata):  # sắp xếp để kết quả không phụ thuộc thứ tự dict
        group = strata[stratum]
        picked += [(item, stratum) for item in rng.sample(group, sample_size(len(group), rate))]
    return picked


def assign_auditors(samples, auditors, conflicts):
    """Chia đều mẫu cho các auditor, tuân thủ luật bốn mắt.

    conflicts(item) → tập user_id không được audit item đó (người annotate / QC1).
    Trả về {item: auditor hoặc None}. Mẫu không có auditor hợp lệ để trống cho PM phân sau.
    """
    load = {a.pk: 0 for a in auditors}
    result = {}
    for item in samples:
        blocked = conflicts(item)
        candidates = [a for a in auditors if a.pk not in blocked]
        if not candidates:
            result[item] = None
            continue
        chosen = min(candidates, key=lambda a: (load[a.pk], a.pk))
        load[chosen.pk] += 1
        result[item] = chosen
    return result
