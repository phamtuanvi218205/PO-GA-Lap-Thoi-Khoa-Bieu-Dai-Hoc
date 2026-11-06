"""Bộ giải mã kiến tạo lịch theo khóa ưu tiên random-key.

Mỗi khối lịch lặp có một khóa ưu tiên; gene phân công giảng viên giữ nguyên.
Decoder mặc định chỉ chọn mẫu hợp lệ theo thứ tự xác định và quay lui khi
bị kẹt. Fitness đánh giá mềm sau khi hoàn tất lịch. Chế độ soft=True giữ
nguyên chính sách lịch sử để replay và làm đối chứng, không dùng cho run mới.
"""

from functools import lru_cache

from . import decoder as original, fitness
from .constraints import validate_timetable, _validate_pairs, _build_session_context
from .encoder import build_recurring_patterns_for_group


class _DecodeContext:
    """Dữ liệu dẫn xuất của đúng một problem/domain bất biến, không phải nghiệm."""

    def __init__(self, problem, domains):
        self.problem = problem
        self.domains = domains
        self.parts = tuple(
            original._part_for_group(problem, group)
            for group in range(problem.schedule_dimension)
        )
        self.patterns = {}
        self.unary_valid = {}
        self.compatibility = {}
        self.session_context = _build_session_context(problem)


class PriorityDecoder:
    """Thứ tự khối do gene quyết định; vị trí mặc định chỉ xét tính hợp lệ.

    Cache gắn với identity của snapshot và domain tuple. Không lưu đáp án của
    candidate để thay thế tìm kiếm; mọi kết quả đều qua Validator đầy đủ.
    """

    def __init__(self, soft: bool = False):
        self.soft = soft
        self.context = None
        self.data = {}
        self.score_cache = {}
        self.preferences = {}
        self.stats = dict(
            decode_calls=0, soft_option_scores=0, score_cache_hits=0,
            pair_checks=0, pattern_features_built=0,
        )
        self.last_order = ()

    def reset_stats(self):
        """Bộ đếm chấm option bao gồm cache hit, không phải full-fitness FE."""
        for key in self.stats:
            self.stats[key] = 0

    def _domain(self, problem, domains, context, group, teacher):
        """Miền mẫu phải hợp lệ ở tất cả tuần và đúng người được gene chọn."""
        key = (group, teacher)
        if key not in context.patterns:
            context.patterns[key] = build_recurring_patterns_for_group(problem, domains, group, teacher)
        patterns = context.patterns[key]
        if key not in context.unary_valid:
            context.unary_valid[key] = tuple(
                i for i, pattern in enumerate(patterns)
                if not original._has_hard_violation(
                    validate_timetable(problem, pattern.session_options)
                )
            )
        return patterns, tuple(sorted(context.unary_valid[key]))

    def _feature(self, problem, context, group, teacher, index):
        """Tính một lần các lượng đóng góp cố định của mẫu vào lịch từng phần."""
        key = (group, teacher, index)
        if key in self.data:
            return self.data[key]
        patterns = context.patterns[group, teacher]
        p = patterns[index]
        by_session = {o.session_index:o for o in p.session_options}
        rooms = {r.location_index for r in problem.rooms}
        physical = sum(o.end_period-o.start_period+1 for o in p.session_options if o.location_index in rooms)
        room_penalty = fitness._calculate_room_discouraged_component(problem, by_session)*physical
        preference_key=(group,teacher)
        if preference_key not in self.preferences:
            penalties = [0.] * len(patterns)
            opportunity = 0.
            for position in range(len(p.session_options)):
                values=[fitness._preference_values_for_option(q.session_options[position],teacher,problem.lecturer_availabilities) for q in patterns]
                preferred = max(v[0] for v in values)
                low = min(v[1] for v in values)
                high = max(v[1] for v in values)
                opportunity+=preferred+high-low
                for j, (a, b) in enumerate(values):
                    penalties[j] += max(0., preferred-a) + max(0., b-low)
            self.preferences[preference_key]=(penalties,opportunity)
        penalties, opportunity = self.preferences[preference_key]
        pref_penalty = penalties[index]
        rows = tuple(((teacher,o.teaching_date),(o.start_period,o.end_period)) for o in p.session_options)
        result = (rows, room_penalty, physical, pref_penalty, opportunity)
        self.data[key] = result
        self.stats['pattern_features_built'] += 1
        return result

    @staticmethod
    @lru_cache(maxsize=65536)
    def day_values(intervals, threshold):
        """Gap, tổng tiết của ngày nhiều buổi, tiết vượt ngưỡng và tổng tải ngày."""
        values = sorted(intervals)
        teach = sum(b-a+1 for a,b in values)
        gaps = sum(max(0,c-b-1) for (_,b),(c,_) in zip(values,values[1:])) if len(values)>1 else 0
        multi = teach if len(values)>1 else 0
        excess = streak = 0
        previous = None
        for a,b in values:
            if previous is not None and a == previous+1:
                streak += b-a+1
            else:
                excess += max(0,streak-threshold)
                streak = b-a+1
            previous = b
        return gaps, multi, excess+max(0,streak-threshold), teach

    def _state(self, problem, context, assigned, teachers):
        """Tổng hợp lịch đã gán để chấm các vị trí tiếp theo bằng hiệu số."""
        days = {}
        room = physical = penalty = opportunity = 0.
        for group,index in assigned.items():
            rows,r,p,n,d = self._feature(problem,context,group,teachers[group],index)
            room += r
            physical += p
            penalty += n
            opportunity += d
            for key, interval in rows:
                days.setdefault(key, []).append(interval)
        threshold = fitness._get_max_consecutive_periods(problem)
        totals = [0,0,0,0]
        for intervals in days.values():
            for i, value in enumerate(self.day_values(tuple(intervals), threshold)):
                totals[i] += value
        return days,totals,room,physical,penalty,opportunity,threshold

    def _score(self, problem, context, assigned, teachers, group, index, state):
        """So thứ tự Q chung rồi mong muốn giờ trên lịch từng phần.

        Không gọi full fitness FE tại đây. Mỗi truy vấn và cache hit được đếm
        riêng vì cùng FE ngoài không có nghĩa cùng tổng chi phí tính toán.
        """
        self.stats['soft_option_scores'] += 1
        cachekey = (tuple(sorted((g,teachers[g],i) for g,i in assigned.items())), group,teachers[group],index)
        if cachekey in self.score_cache:
            self.stats['score_cache_hits'] += 1
            return self.score_cache[cachekey]
        days,totals,room,physical,penalty,opportunity,threshold = state
        totals = list(totals)
        rows,r,p,n,d = self._feature(problem,context,group,teachers[group],index)
        for key,interval in rows:
            previous = tuple(days.get(key,()))
            before = self.day_values(previous, threshold)
            after = self.day_values(previous+(interval,), threshold)
            for j in range(4):
                totals[j] += after[j]-before[j]
        gaps,multi,excess,teach = totals
        general = (fitness._get_soft_weight(problem,'SOFT_LECTURER_GAP')*(gaps/(gaps+multi) if gaps+multi else 0)
            +fitness._get_soft_weight(problem,'SOFT_LECTURER_CONSECUTIVE')*(excess/teach if teach else 0)
            +fitness._get_soft_weight(problem,'SOFT_ROOM_DISCOURAGED')*((room+r)/(physical+p) if physical+p else 0))
        # Tải và độ phù hợp môn không đổi giữa các vị trí khi đã chọn người.
        # Mẫu lặp cố định không đổi phòng giữa tuần. Các phần đó vẫn được tính
        # trong fitness cuối nhưng không phân biệt các vị trí đang thử ở đây.
        lecturer = (penalty+n)/(opportunity+d) if opportunity+d else 0.
        if fitness._get_soft_weight(problem,'SOFT_LECTURER_TIME_PREFERENCE') == 0:
            lecturer = 0.
        result = (general,lecturer)
        if len(self.score_cache) >= 100000:
            self.score_cache.clear()
        self.score_cache[cachekey] = result
        return result

    def __call__(self, problem, option_domains, vector, max_decode_nodes):
        """Kiến tạo theo priority thuần; không MRV, không thay công thức GA/PO."""
        problem = original.historical_problem(problem)
        original._validate_decode_inputs(problem,option_domains,vector,max_decode_nodes)
        self.stats['decode_calls'] += 1
        cacheable = isinstance(option_domains, tuple) and all(isinstance(d, tuple) for d in option_domains)
        context = self.context
        if (not cacheable or context is None or context.problem is not problem
                or context.domains is not option_domains):
            context = _DecodeContext(problem, option_domains)
        if self.context is not context:
            self.context = context
            self.data.clear()
            self.score_cache.clear()
            self.preferences.clear()
        if any(not domain for domain in option_domains):
            return original.decode_direct_vector(problem,option_domains,vector,max_decode_nodes)
        by_section,selected,failure=original._select_lecturers(problem,vector)
        if failure is not None:
            return failure
        failure=original._load_failure(problem,by_section,selected)
        if failure is not None:
            return failure
        teachers = []
        active = []
        valid = []
        for g,part in enumerate(context.parts):
            teacher = by_section[problem.assignment_key_for_part(part)]
            teachers.append(teacher)
            patterns,indices=self._domain(problem,option_domains,context,g,teacher)
            if not indices:
                return original.DecodeResult(original.DecodeStatus.DECODE_FAILED,(),(),(),0,0,
                    problem.schedule_groups[g][0], 'Không có mẫu lặp hợp lệ tĩnh.', selected)
            active.append(patterns)
            valid.append(indices)
        priority=tuple(sorted(range(problem.schedule_dimension),key=lambda g:(
            vector[problem.schedule_gene_offset+g],
            min(problem.class_sessions[s].class_session_id for s in problem.schedule_groups[g]))))
        self.last_order=priority
        assigned = {}
        nodes = backtracks = 0
        failed = None
        exhausted = False

        def compatible(g,i,h,j):
            """Cache chỉ có điều kiện cặp trên mọi ngày chung, có khóa người dạy."""
            if g > h:
                g, h, i, j = h, g, j, i
            key=(g,teachers[g],i,h,teachers[h],j)
            if key not in context.compatibility:
                if len(context.compatibility) >= 100000:
                    context.compatibility.clear()
                a,b=active[g][i],active[h][j]
                if a.iso_weekday != b.iso_weekday:
                    answer = True
                else:
                    first = {o.teaching_date: o for o in a.session_options}
                    second = {o.teaching_date: o for o in b.session_options}
                    answer=all(not _validate_pairs(problem,(first[d],second[d]),context.session_context) for d in first.keys()&second.keys())
                context.compatibility[key] = answer
                self.stats['pair_checks'] += 1
            return context.compatibility[key]

        def search(depth):
            """Dừng ở lịch hợp lệ đầu tiên, không tìm lịch có điểm mềm thấp nhất.

            Quay lui chỉ khi nhánh hiện tại không hoàn tất được lịch. Thứ tự
            khối không đổi; ngân sách node áp dụng cả lần gán phải bỏ lại.
            """
            nonlocal nodes,backtracks,failed,exhausted
            if depth==len(priority):
                options=tuple(o for g,i in assigned.items() for o in active[g][i].session_options)
                return validate_timetable(problem,options).is_valid
            g=priority[depth]
            possible=[i for i in valid[g] if all(compatible(g,i,h,j) for h,j in assigned.items())]
            if self.soft and possible:
                state=self._state(problem,context,assigned,teachers)
                possible.sort(key=lambda i:(self._score(problem,context,assigned,teachers,g,i,state),
                    active[g][i].iso_weekday,active[g][i].start_period,active[g][i].location_index,i))
            else:
                # Không đọc preference, trọng số hay tính soft fitness. Index
                # cuối là tie-break của miền mẫu đã sinh một cách xác định.
                possible.sort(key=lambda i:(active[g][i].iso_weekday,
                    active[g][i].start_period,active[g][i].location_index,i))
            for i in possible:
                if nodes >= max_decode_nodes:
                    exhausted = True
                    failed = g
                    return False
                nodes += 1
                assigned[g] = i
                if search(depth+1):
                    return True
                del assigned[g]
                backtracks += 1
                if exhausted:
                    return False
            failed = g
            return False

        if not search(0):
            return original.DecodeResult(original.DecodeStatus.DECODE_FAILED,(),(),(),nodes,backtracks,
                problem.schedule_groups[failed][0] if failed is not None else None,
                'Đã hết max_decode_nodes khi kiến tạo lịch ưu tiên.' if exhausted else 'Không ghép được các mẫu theo thứ tự ưu tiên.',selected)
        by_session = {}
        raw = {}
        for g,i in assigned.items():
            for option, index in zip(active[g][i].session_options, active[g][i].raw_option_indices):
                by_session[option.session_index] = option
                raw[option.session_index] = index
        # Giữ khóa ưu tiên, không đổi genotype về chỉ số option đã được chọn.
        return original.DecodeResult(original.DecodeStatus.SUCCESS,
            tuple(by_session[i] for i in range(problem.session_dimension)),
            tuple(raw[i] for i in range(problem.session_dimension)),tuple(vector),nodes,backtracks,None,
            'Lịch ưu tiên kiến tạo đã được kiểm tra trên toàn bộ tuần hoạt động.',selected)

    def direct_vector(self, problem, domains, individual):
        """Vector DIRECT tương đương chỉ phục vụ hậu kiểm/đọc lịch sử, không tiến hóa."""
        by_section,_,failure=original._select_lecturers(problem,individual.vector)
        assert failure is None
        result=list(individual.vector[:problem.assignment_dimension])
        for g,sessions in enumerate(problem.schedule_groups):
            part=original._part_for_group(problem,g); patterns=build_recurring_patterns_for_group(problem,domains,g,by_section[problem.assignment_key_for_part(part)])
            target=tuple(individual.selected_options[s] for s in sessions)
            index=next(i for i,p in enumerate(patterns) if p.session_options==target)
            result.append((index+.5)/len(patterns))
        return tuple(result)
