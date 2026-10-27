"""Nghiệp vụ chuẩn bị phương án giảng dạy trước khi chạy optimizer.

Module này là bản Python tương đương với package ``planning`` trước đây của
ứng dụng Java. Nó chỉ xử lý dữ liệu nghiệp vụ thuần túy, không truy cập cơ sở
dữ liệu và không gọi GA, PO hoặc GA–PO. Việc tách riêng giúp các quy tắc sinh
plan, mở rộng session và tạo scenario có thể được kiểm thử độc lập.
"""

from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush
from hashlib import sha256
from math import ceil
import re
from typing import Mapping, Sequence

from ..core.models import LocationType, ScenarioScopeType, TeachingPlanStatus


# Đưa phiên bản thuật toán sinh plan vào generation key để dữ liệu đã sinh
# bằng quy tắc cũ không bị tái sử dụng sau khi quy tắc phân bố tuần thay đổi.
TEACHING_PLAN_GENERATOR_VERSION = "CONTIGUOUS_WINDOWS_V2"


@dataclass(frozen=True, slots=True)
class TeachingPlanGenerationRequest:
    """Hợp đồng đầu vào bất biến của bộ sinh phương án giảng dạy."""

    part_code: str
    total_periods: int
    start_week_number: int
    end_week_number: int
    allowed_durations: tuple[int, ...]
    max_sessions_per_week: int
    allows_intensive: bool
    max_candidate_plans: int

    def __post_init__(self) -> None:
        if not self.part_code or not self.part_code.strip():
            raise ValueError("Mã phần giảng dạy không được để trống.")
        if self.total_periods <= 0:
            raise ValueError("Tổng số tiết phải lớn hơn 0.")
        if self.start_week_number < 1 or self.end_week_number < self.start_week_number:
            raise ValueError("Khoảng tuần được phép không hợp lệ.")
        if not self.allowed_durations:
            raise ValueError("Phải có ít nhất một thời lượng được phép.")

        normalized_durations = tuple(sorted(set(self.allowed_durations)))
        if any(duration <= 0 for duration in normalized_durations):
            raise ValueError("Mọi thời lượng được phép phải lớn hơn 0.")
        object.__setattr__(self, "allowed_durations", normalized_durations)

        if self.max_sessions_per_week <= 0:
            raise ValueError("Số buổi tối đa mỗi tuần phải lớn hơn 0.")
        if self.max_candidate_plans <= 0:
            raise ValueError("Số plan ứng viên tối đa phải lớn hơn 0.")

    @property
    def week_count(self) -> int:
        """Số tuần liên tiếp mà phần giảng dạy được phép hoạt động."""

        return self.end_week_number - self.start_week_number + 1


@dataclass(frozen=True, slots=True)
class GeneratedTeachingPlanItem:
    """Một buổi dự kiến của plan trước khi được lưu thành ClassSession."""

    item_number: int
    week_number: int
    session_order_in_week: int
    duration_periods: int
    stability_group_no: int

    def __post_init__(self) -> None:
        if self.item_number < 1 or self.week_number < 1 or self.session_order_in_week < 1:
            raise ValueError("Số thứ tự item, tuần và buổi phải bắt đầu từ 1.")
        if self.duration_periods < 1 or self.stability_group_no < 1:
            raise ValueError("Thời lượng và nhóm ổn định phải lớn hơn 0.")


@dataclass(frozen=True, slots=True)
class GeneratedTeachingPlan:
    """Một TeachingPlan hợp lệ được hệ thống sinh hoàn toàn tự động."""

    sequence_number: int
    plan_code: str
    plan_name: str
    intensive: bool
    items: tuple[GeneratedTeachingPlanItem, ...]

    def __post_init__(self) -> None:
        if self.sequence_number < 1:
            raise ValueError("Số thứ tự plan phải bắt đầu từ 1.")
        if not self.plan_code.strip() or not self.plan_name.strip():
            raise ValueError("Plan phải có mã và tên.")
        object.__setattr__(self, "items", tuple(self.items))
        if not self.items:
            raise ValueError("Plan phải có ít nhất một buổi.")

    @property
    def total_periods(self) -> int:
        """Tổng số tiết của tất cả buổi trong plan."""

        return sum(item.duration_periods for item in self.items)

    @property
    def status(self) -> TeachingPlanStatus:
        """Plan sinh thành công luôn ở trạng thái VALID."""

        return TeachingPlanStatus.VALID


@dataclass(frozen=True, slots=True)
class ExpandedClassSession:
    """Một lần xuất hiện theo tuần được mở rộng từ plan, trước persistence."""

    session_number: int
    week_number: int
    duration_periods: int
    stability_group_no: int
    required_location_type: LocationType


@dataclass(frozen=True, slots=True)
class ScenarioPlanCandidate:
    """Một plan có thể được chọn cho một TeachingPart trong scenario."""

    teaching_part_id: int
    teaching_plan_id: int
    candidate_rank: int
    intensive: bool

    def __post_init__(self) -> None:
        if self.teaching_part_id <= 0 or self.teaching_plan_id <= 0 or self.candidate_rank <= 0:
            raise ValueError("Định danh và thứ hạng plan phải lớn hơn 0.")


@dataclass(frozen=True, slots=True)
class GeneratedScenarioSelection:
    """Một tổ hợp plan hữu hạn dùng để tạo PlanningScenario ứng viên."""

    candidate_rank: int
    plan_rank_penalty: int
    plans: tuple[ScenarioPlanCandidate, ...]

    def __post_init__(self) -> None:
        if self.candidate_rank <= 0 or self.plan_rank_penalty < 0:
            raise ValueError("Thứ hạng scenario không hợp lệ.")
        object.__setattr__(self, "plans", tuple(self.plans))
        if not self.plans:
            raise ValueError("Scenario phải chọn ít nhất một plan.")


@dataclass(frozen=True, slots=True)
class AutomaticScenarioRequest:
    """Hợp đồng tạo hữu hạn PlanningScenario hoàn toàn tự động."""

    term_code: str
    scope_type: ScenarioScopeType
    teaching_part_ids: frozenset[int] = frozenset()
    max_scenario_candidates: int = 10

    def __post_init__(self) -> None:
        if not self.term_code or not self.term_code.strip():
            raise ValueError("Học kỳ là bắt buộc.")
        normalized_part_ids = frozenset(self.teaching_part_ids or ())
        object.__setattr__(self, "teaching_part_ids", normalized_part_ids)
        if self.scope_type == ScenarioScopeType.SUBSET and not self.teaching_part_ids:
            raise ValueError("Scenario SUBSET phải chỉ rõ TeachingPart.")
        if self.scope_type == ScenarioScopeType.FULL_TERM and self.teaching_part_ids:
            raise ValueError("Scenario FULL_TERM tự lấy toàn bộ phần giảng dạy được công bố.")
        if self.max_scenario_candidates <= 0:
            raise ValueError("Số scenario ứng viên tối đa phải lớn hơn 0.")


@dataclass(frozen=True, slots=True)
class _CandidatePlan:
    """Biểu diễn nội bộ trước khi generator gán mã và thứ tự chính thức."""

    intensive: bool
    items: tuple[GeneratedTeachingPlanItem, ...]
    signature: str


class TeachingPlanGenerator:
    """Sinh các cách chia tổng số tiết thành buổi theo rule đầu vào.

    Generator không quyết định giảng viên, thứ, tiết hoặc phòng. Mỗi tổ hợp
    thời lượng hợp lệ được đặt vào một khoảng tuần liên tục. Khoảng này có thể
    bắt đầu ở bất kỳ tuần hợp lệ nào nhưng không được vượt quá hạn của học kỳ.
    Khi rule cho phép học tăng tốc, generator sinh thêm phương án có nhiều
    buổi trong một tuần. Kết quả được loại trùng và sắp thứ tự xác định.
    """

    def generate(self, request: TeachingPlanGenerationRequest) -> tuple[GeneratedTeachingPlan, ...]:
        if request is None:
            raise ValueError("Yêu cầu sinh plan không được null.")

        duration_combinations: list[tuple[int, ...]] = []
        self._enumerate_duration_combinations(
            request.allowed_durations,
            duration_index=0,
            remaining_periods=request.total_periods,
            counts=[0] * len(request.allowed_durations),
            output=duration_combinations,
        )

        available_slot_count = request.week_count * request.max_sessions_per_week
        feasible_combinations = tuple(
            durations
            for durations in duration_combinations
            if durations and len(durations) <= available_slot_count
        )
        if not feasible_combinations:
            return ()

        # Tổ hợp có nhiều buổi nhất là nhịp học thông thường. Các tổ hợp dùng
        # buổi dài hơn hoặc dồn nhiều buổi/tuần được đánh dấu là tăng tốc.
        maximum_session_count = max(
            len(durations) for durations in feasible_combinations
        )
        unique_candidates: dict[str, _CandidatePlan] = {}

        for durations in feasible_combinations:
            composition_is_intensive = len(durations) < maximum_session_count
            if composition_is_intensive and not request.allows_intensive:
                continue

            # Phương án một buổi mỗi tuần: mọi tuần từ lúc bắt đầu đến lúc kết
            # thúc đều có buổi học, không còn kiểu tuần 1, 3, 4, 6...
            if len(durations) <= request.week_count:
                normal_slots = self._continuous_slots(
                    len(durations), len(durations), request.max_sessions_per_week
                )
                self._add_all_start_windows(
                    request=request,
                    durations=durations,
                    selected_slots=normal_slots,
                    active_week_count=len(durations),
                    intensive=composition_is_intensive,
                    output=unique_candidates,
                )

            # Khi được phép tăng tốc, dồn theo đúng giới hạn số buổi/tuần rồi
            # dịch cả khoảng liên tục qua mọi tuần bắt đầu còn hợp lệ.
            if request.allows_intensive and request.max_sessions_per_week > 1:
                compact_week_count = ceil(
                    len(durations) / request.max_sessions_per_week
                )
                if (
                    compact_week_count < len(durations)
                    and compact_week_count <= request.week_count
                ):
                    compact_slots = self._continuous_slots(
                        len(durations), compact_week_count, request.max_sessions_per_week
                    )
                    self._add_all_start_windows(
                        request=request,
                        durations=durations,
                        selected_slots=compact_slots,
                        active_week_count=compact_week_count,
                        intensive=True,
                        output=unique_candidates,
                    )

        sorted_candidates = sorted(
            unique_candidates.values(),
            key=lambda candidate: (
                candidate.intensive,
                -len(candidate.items),
                candidate.items[0].week_number,
                candidate.items[-1].week_number,
                candidate.signature,
            ),
        )[: request.max_candidate_plans]

        return tuple(
            GeneratedTeachingPlan(
                sequence_number=index,
                plan_code=self._build_plan_code(request.part_code, index),
                plan_name=self._build_plan_name(candidate),
                intensive=candidate.intensive,
                items=candidate.items,
            )
            for index, candidate in enumerate(sorted_candidates, start=1)
        )

    def _enumerate_duration_combinations(
        self,
        allowed_durations: tuple[int, ...],
        duration_index: int,
        remaining_periods: int,
        counts: list[int],
        output: list[tuple[int, ...]],
    ) -> None:
        duration = allowed_durations[duration_index]
        if duration_index == len(allowed_durations) - 1:
            if remaining_periods % duration == 0:
                counts[duration_index] = remaining_periods // duration
                output.append(self._expand_duration_counts(allowed_durations, counts))
                counts[duration_index] = 0
            return

        maximum_count = remaining_periods // duration
        for count in range(maximum_count, -1, -1):
            counts[duration_index] = count
            self._enumerate_duration_combinations(
                allowed_durations,
                duration_index + 1,
                remaining_periods - count * duration,
                counts,
                output,
            )
        counts[duration_index] = 0

    @staticmethod
    def _expand_duration_counts(
        durations: tuple[int, ...], counts: Sequence[int]
    ) -> tuple[int, ...]:
        return tuple(
            duration
            for duration, count in zip(durations, counts, strict=True)
            for _ in range(count)
        )

    @staticmethod
    def _continuous_slots(
        session_count: int, active_week_count: int, max_sessions_per_week: int
    ) -> tuple[int, ...]:
        """Phân buổi vào các tuần liên tục, không để tuần trống ở giữa."""

        if active_week_count <= 0 or active_week_count > session_count:
            raise ValueError("Số tuần hoạt động không phù hợp với số buổi.")

        base_count, remainder = divmod(session_count, active_week_count)
        weekly_counts = [base_count] * active_week_count

        # Rải các buổi dư tương đối đều giữa khoảng học thay vì dồn hết vào
        # tuần đầu. Mọi tuần vẫn có ít nhất một buổi.
        for extra_index in range(remainder):
            week_index = ((extra_index + 1) * active_week_count) // (remainder + 1)
            weekly_counts[week_index] += 1

        if max(weekly_counts) > max_sessions_per_week:
            raise ValueError("Phân bố buổi vượt quá giới hạn của một tuần.")

        return tuple(
            week_index * max_sessions_per_week + session_order
            for week_index, count in enumerate(weekly_counts)
            for session_order in range(count)
        )

    @classmethod
    def _add_all_start_windows(
        cls,
        *,
        request: TeachingPlanGenerationRequest,
        durations: tuple[int, ...],
        selected_slots: tuple[int, ...],
        active_week_count: int,
        intensive: bool,
        output: dict[str, _CandidatePlan],
    ) -> None:
        latest_start_week = request.end_week_number - active_week_count + 1
        for start_week_number in range(request.start_week_number, latest_start_week + 1):
            candidate = cls._build_candidate(
                request=request,
                durations=durations,
                selected_slots=selected_slots,
                start_week_number=start_week_number,
                intensive=intensive,
            )
            output.setdefault(candidate.signature, candidate)

    @staticmethod
    def _build_candidate(
        request: TeachingPlanGenerationRequest,
        durations: tuple[int, ...],
        selected_slots: tuple[int, ...],
        start_week_number: int,
        intensive: bool,
    ) -> _CandidatePlan:
        items = tuple(
            GeneratedTeachingPlanItem(
                item_number=index + 1,
                week_number=start_week_number
                + selected_slots[index] // request.max_sessions_per_week,
                session_order_in_week=selected_slots[index] % request.max_sessions_per_week + 1,
                duration_periods=duration,
                stability_group_no=selected_slots[index] % request.max_sessions_per_week + 1,
            )
            for index, duration in enumerate(durations)
        )
        signature = "|".join(
            f"{item.week_number}:{item.session_order_in_week}:{item.duration_periods}"
            for item in items
        )
        return _CandidatePlan(
            intensive=intensive,
            items=items,
            signature=signature,
        )

    @staticmethod
    def _build_plan_code(part_code: str, sequence_number: int) -> str:
        normalized = re.sub(r"[^A-Z0-9]+", "_", part_code.strip().upper()).strip("_")
        return f"{normalized}_AUTO_{sequence_number:02d}"

    @staticmethod
    def _build_plan_name(candidate: _CandidatePlan) -> str:
        duration_counts: dict[int, int] = {}
        for item in candidate.items:
            duration_counts[item.duration_periods] = duration_counts.get(item.duration_periods, 0) + 1
        composition = " + ".join(
            f"{count} buổi x {duration} tiết"
            for duration, count in sorted(duration_counts.items())
        )
        schedule_type = "tăng tốc" if candidate.intensive else "thông thường"
        first_week = candidate.items[0].week_number
        last_week = candidate.items[-1].week_number
        week_range = (
            f"tuần {first_week}"
            if first_week == last_week
            else f"tuần {first_week}-{last_week}"
        )
        return f"Tự động: {composition} ({schedule_type}, {week_range} liên tục)"


def create_plan_generation_key(
    *,
    term_code: str,
    part_code: str,
    part_type: str,
    total_periods: int,
    required_location_type: str,
    start_week_number: int,
    end_week_number: int,
    max_sessions_per_week: int,
    allows_intensive: bool,
    max_candidate_plans: int,
    allowed_durations: Sequence[int],
) -> str:
    """Tạo khóa SHA-256 xác định cho dữ liệu đầu vào và phiên bản generator.

    Khóa thay đổi khi dữ liệu đầu vào hoặc quy tắc sinh plan thay đổi, nhờ đó
    persistence không tái sử dụng plan của phiên bản cũ. Chuỗi hex viết hoa để
    khớp check constraint của SQL Server.
    """

    canonical_value = "|".join(
        (
            TEACHING_PLAN_GENERATOR_VERSION,
            term_code,
            part_code,
            part_type,
            str(total_periods),
            required_location_type,
            str(start_week_number),
            str(end_week_number),
            str(max_sessions_per_week),
            str(allows_intensive).lower(),
            str(max_candidate_plans),
            ",".join(str(value) for value in sorted(allowed_durations)),
        )
    )
    return sha256(canonical_value.encode("utf-8")).hexdigest().upper()


class SessionExpander:
    """Mở rộng item của plan thành các lần xuất hiện theo tuần."""

    def expand(
        self,
        plan: GeneratedTeachingPlan,
        required_location_type: LocationType,
    ) -> tuple[ExpandedClassSession, ...]:
        if plan is None:
            raise ValueError("Plan không được null.")
        if required_location_type is None:
            raise ValueError("Loại địa điểm không được null.")

        return tuple(
            ExpandedClassSession(
                session_number=item.item_number,
                week_number=item.week_number,
                duration_periods=item.duration_periods,
                stability_group_no=item.stability_group_no,
                required_location_type=required_location_type,
            )
            for item in plan.items
        )


class PlanningScenarioCandidatePlanner:
    """Sinh hữu hạn các tổ hợp plan tốt nhất mà không tạo toàn tích Descartes."""

    def generate(
        self,
        candidates_by_part: Mapping[int, Sequence[ScenarioPlanCandidate]],
        max_scenario_candidates: int,
    ) -> tuple[GeneratedScenarioSelection, ...]:
        if not candidates_by_part:
            raise ValueError("Phải có plan ứng viên cho ít nhất một TeachingPart.")
        if max_scenario_candidates <= 0:
            raise ValueError("Số scenario ứng viên tối đa phải lớn hơn 0.")

        part_ids = tuple(sorted(candidates_by_part))
        ordered_candidates: list[tuple[ScenarioPlanCandidate, ...]] = []
        for part_id in part_ids:
            plans = tuple(sorted(
                candidates_by_part[part_id],
                key=lambda plan: (plan.candidate_rank, plan.intensive, plan.teaching_plan_id),
            ))
            if not plans:
                raise ValueError(f"TeachingPart {part_id} không có plan VALID.")
            if any(plan.teaching_part_id != part_id for plan in plans):
                raise ValueError(f"Danh sách plan không thuộc đúng TeachingPart {part_id}.")
            ordered_candidates.append(plans)

        initial_indexes = (0,) * len(part_ids)
        queue: list[tuple[int, int, str, tuple[int, ...]]] = []
        self._push_state(queue, initial_indexes, ordered_candidates)
        visited = {initial_indexes}
        result: list[GeneratedScenarioSelection] = []

        while queue and len(result) < max_scenario_candidates:
            penalty, _, _, indexes = heappop(queue)
            selection = tuple(
                ordered_candidates[part_index][indexes[part_index]]
                for part_index in range(len(part_ids))
            )
            result.append(GeneratedScenarioSelection(
                candidate_rank=len(result) + 1,
                plan_rank_penalty=penalty,
                plans=selection,
            ))

            for part_index in range(len(part_ids)):
                next_index = indexes[part_index] + 1
                if next_index >= len(ordered_candidates[part_index]):
                    continue
                neighbor = list(indexes)
                neighbor[part_index] = next_index
                neighbor_indexes = tuple(neighbor)
                if neighbor_indexes not in visited:
                    visited.add(neighbor_indexes)
                    self._push_state(queue, neighbor_indexes, ordered_candidates)

        return tuple(result)

    @classmethod
    def _push_state(
        cls,
        queue: list[tuple[int, int, str, tuple[int, ...]]],
        indexes: tuple[int, ...],
        candidates: Sequence[Sequence[ScenarioPlanCandidate]],
    ) -> None:
        penalty = sum(
            candidates[part_index][index].candidate_rank - 1
            for part_index, index in enumerate(indexes)
        )
        intensive_count = sum(
            candidates[part_index][index].intensive
            for part_index, index in enumerate(indexes)
        )
        signature = ",".join(str(index) for index in indexes)
        heappush(queue, (penalty, intensive_count, signature, indexes))
