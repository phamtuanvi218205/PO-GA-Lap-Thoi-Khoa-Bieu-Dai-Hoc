"""Giải mã Priority + Placement bằng tìm kiếm chỉ xét ràng buộc cứng.

PriorityKey quyết định thứ tự khối; PlacementKey chọn hạng trong tập mẫu
hiện khả thi. Khi bế tắc, thử hạng lân cận để hoàn tất lịch trong ngân sách
node. Không đọc điểm mềm và không tìm lịch có fitness thấp nhất.
"""

from math import floor

from . import decoder as original
from .priority_decoder import PriorityDecoder, _DecodeContext
from .constraints import validate_timetable, _validate_pairs


def relative_indices(key, count):
    """Map into the current feasible list, then try nearest list positions.

    Exact order k,k+1,k-1,k+2,k-2,... within bounds. This is a deterministic
    ordering of feasible-list ranks, not a distance in time/room or soft cost.
    """
    if count < 1:
        return ()
    preferred = min(floor(key*count), count-1)
    return tuple(sorted(range(count), key=lambda i:(abs(i-preferred), 0 if i>=preferred else 1)))


class PlacementDecoder(PriorityDecoder):
    """Khóa ưu tiên chọn thứ tự; khóa vị trí chọn trong tập khả thi hiện tại."""

    def __init__(self):
        super().__init__(soft=False)
        self.last_vector = None
        self.last_decisions = ()
        self.last_success = False
        self.stats.update(successful_decodes=0, final_block_placements=0,
                          backtrack_override_placement_count=0, changed_feasible_context_count=0)

    def __call__(self, problem, domains, vector, max_decode_nodes):
        original._validate_decode_inputs(problem, domains, vector, max_decode_nodes)
        if problem.dimension != problem.assignment_dimension + 2 * problem.schedule_dimension:
            raise ValueError('Priority + Placement yêu cầu cấu trúc gene L+2B.')
        self.stats['decode_calls'] += 1
        self.last_vector = tuple(vector); self.last_decisions = (); self.last_success = False
        self.last_order = ()
        if any(not domain for domain in domains):
            # Legacy function only diagnoses an empty domain and returns before
            # placement selection; it does not map any scheduling gene here.
            return original.decode_direct_vector(problem, domains, vector, max_decode_nodes)
        context = self.context
        cacheable = isinstance(domains, tuple) and all(isinstance(d, tuple) for d in domains)
        if not cacheable or context is None or context.problem is not problem or context.domains is not domains:
            context = self.context = _DecodeContext(problem, domains)
        by_section, selected, failure = original._select_lecturers(problem, vector)
        if failure is not None:
            return failure
        failure = original._load_failure(problem, by_section, selected)
        if failure is not None:
            return failure
        teachers = []; active = []; valid = []
        for g, part in enumerate(context.parts):
            teacher = by_section[problem.assignment_key_for_part(part)]
            teachers.append(teacher)
            patterns, indices = self._domain(problem, domains, context, g, teacher)
            if not indices:
                return original.DecodeResult(original.DecodeStatus.DECODE_FAILED, (), (), (), 0, 0,
                    problem.schedule_groups[g][0], 'No static recurring pattern for the chosen lecturer.', selected)
            active.append(patterns); valid.append(indices)
        priority = tuple(sorted(range(problem.schedule_dimension), key=lambda g:(
            vector[problem.schedule_gene_offset+g],
            min(problem.class_sessions[s].class_session_id for s in problem.schedule_groups[g]))))
        self.last_order = priority
        assigned = {}; decisions = {}; first_preferred = {}
        nodes = backtracks = 0; failed = None; exhausted = False

        def compatible(g, i, h, j):
            if g > h:
                g, h, i, j = h, g, j, i
            key = (g, teachers[g], i, h, teachers[h], j)
            if key not in context.compatibility:
                if len(context.compatibility) >= 100000:
                    context.compatibility.clear()
                a, b = active[g][i], active[h][j]
                if a.iso_weekday != b.iso_weekday:
                    answer = True
                else:
                    first = {o.teaching_date:o for o in a.session_options}
                    second = {o.teaching_date:o for o in b.session_options}
                    answer = all(not _validate_pairs(problem, (first[d], second[d]), context.session_context)
                                 for d in first.keys() & second.keys())
                context.compatibility[key] = answer
                self.stats['pair_checks'] += 1
            return context.compatibility[key]

        def search(depth):
            """Dừng ở lịch hợp lệ đầu tiên; không so điểm mềm giữa các nhánh.

            PlacementKey xác định hạng ưu tiên trong ngữ cảnh hiện tại. Chỉ
            thử hạng lân cận khi nhánh trước không thể hoàn tất lịch; mọi lần
            gán bị bỏ cũng tiêu tốn ngân sách node.
            """
            nonlocal nodes, backtracks, failed, exhausted
            if depth == len(priority):
                options = tuple(o for g, i in assigned.items() for o in active[g][i].session_options)
                return validate_timetable(problem, options).is_valid
            g = priority[depth]
            possible = [i for i in valid[g] if all(compatible(g, i, h, j) for h, j in assigned.items())]
            possible.sort(key=lambda i:(active[g][i].iso_weekday, active[g][i].start_period,
                                        active[g][i].location_index, i))
            # Tập này đã loại các xung đột với khối trước, nên hạng không
            # đồng nghĩa với option_index trong miền encoder tĩnh.
            key = vector[problem.placement_gene_offset+g]
            ranks = relative_indices(key, len(possible))
            if ranks:
                preferred = possible[ranks[0]]
                first_preferred.setdefault(g, preferred)
            for rank in ranks:
                if nodes >= max_decode_nodes:
                    exhausted = True; failed = g
                    return False
                nodes += 1; index = possible[rank]; assigned[g] = index
                decisions[g] = dict(group=g, placement_key=key, feasible_count=len(possible),
                    preferred_rank=ranks[0], chosen_rank=rank, preferred_raw_pattern=preferred,
                    chosen_raw_pattern=index, overridden=index != preferred,
                    first_visited_preferred_raw_pattern=first_preferred[g],
                    preferred_changed_with_context=preferred != first_preferred[g])
                if search(depth+1):
                    return True
                del assigned[g]; del decisions[g]; backtracks += 1
                if exhausted:
                    return False
            failed = g
            return False

        if not search(0):
            return original.DecodeResult(original.DecodeStatus.DECODE_FAILED, (), (), (), nodes, backtracks,
                problem.schedule_groups[failed][0] if failed is not None else None,
                'Đã hết max_decode_nodes khi giải mã Priority + Placement.' if exhausted else 'Không tìm thấy nhánh hoàn chỉnh hợp lệ.', selected)
        by_session = {}; raw = {}
        for g, i in assigned.items():
            for option, index in zip(active[g][i].session_options, active[g][i].raw_option_indices):
                by_session[option.session_index] = option; raw[option.session_index] = index
        self.last_decisions = tuple(decisions[g] for g in priority)
        self.last_success = True
        self.stats['successful_decodes'] += 1
        self.stats['final_block_placements'] += len(priority)
        self.stats['backtrack_override_placement_count'] += sum(d['overridden'] for d in self.last_decisions)
        self.stats['changed_feasible_context_count'] += sum(d['preferred_changed_with_context'] for d in self.last_decisions)
        return original.DecodeResult(original.DecodeStatus.SUCCESS,
            tuple(by_session[i] for i in range(problem.session_dimension)),
            tuple(raw[i] for i in range(problem.session_dimension)), tuple(vector), nodes, backtracks,
            None, 'Priority and relative placement keys produced a hard-valid recurring timetable.', selected)
