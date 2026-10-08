"""Các hợp đồng số liệu dùng chung cho GA, PO và GA–PO.

Các optimizer của bài toán thời khóa biểu phải được so sánh trên cùng cách đếm
Fitness Evaluation (FE) và cùng thứ tự fitness Gate F. Module này định nghĩa
các cấu trúc dữ liệu và phép cộng số liệu trung lập với thuật toán để GA, PO
và pipeline lai không tự tạo ba định dạng hoặc ba quy tắc đếm khác nhau.

Một mốc hội tụ không cộng ba score thành một giá trị vô hướng. Project đánh giá
lịch hợp lệ theo thứ tự lexicographic ``Q_time -> Q_general -> Q_lecturer``;
vì vậy cả ba thành phần phải được lưu riêng trong mọi mốc.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite

from .models import OptimizationAlgorithm
from .population import (
    CandidateEvaluationResult,
    CandidateEvaluationStatus,
    TimetableIndividual,
)
from .repair import RepairStatus


@dataclass(frozen=True, slots=True)
class ConvergencePoint:
    """Một mốc ghi nhận nghiệm tốt nhất đã tìm được trong quá trình tối ưu.

    Attributes:
        iteration: Vòng lặp tạo ra mốc. Quần thể ban đầu được ghi tại
            ``iteration = 0`` vì chưa áp dụng toán tử GA hoặc công thức PO.
        fitness_evaluations: Tổng số lần Fitness thực sự được gọi tính đến mốc
            này. Decode/repair thất bại trước Fitness không làm tăng FE.
        time_stability_score: ``Q_time`` của lịch tốt nhất từng gặp; đây là tầng
            ưu tiên cao nhất, thể hiện độ ổn định thứ và tiết bắt đầu.
        general_quality_score: ``Q_general`` của lịch tốt nhất từng gặp, gồm
            sức chứa, khoảng trống, phòng không khuyến khích và đổi phòng nhẹ.
        lecturer_preference_score: ``Q_lecturer`` của lịch tốt nhất từng gặp,
            chỉ được xét sau hai tầng chất lượng phía trên.

    Class này chỉ lưu một ảnh chụp số liệu. Nó không tự chọn cá thể tốt nhất,
    không tính fitness và không quyết định khi nào optimizer phải dừng.
    """

    iteration: int
    fitness_evaluations: int
    time_stability_score: float
    general_quality_score: float
    lecturer_preference_score: float

    def __post_init__(self) -> None:
        """Từ chối mốc hội tụ không thể xuất hiện trong một lần chạy hợp lệ."""

        # Iteration 0 dành cho quần thể ban đầu; giá trị âm không có ý nghĩa.
        if self.iteration < 0:
            raise ValueError("iteration không được âm.")

        # Một mốc chỉ được ghi sau khi đã có ít nhất một lịch được Fitness đánh
        # giá. Trạng thái chưa có lịch thuộc kết quả cấp run, không phải một mốc
        # convergence giả với FE bằng 0.
        if self.fitness_evaluations < 1:
            raise ValueError(
                "fitness_evaluations phải lớn hơn hoặc bằng 1."
            )

        scores = (
            self.time_stability_score,
            self.general_quality_score,
            self.lecturer_preference_score,
        )

        # Các công thức Gate F tạo score hữu hạn và không âm. NaN, vô cực hoặc
        # số âm thường cho biết dữ liệu đầu vào hay phép chuẩn hóa bị lỗi; không
        # được ghi chúng vào lịch sử hội tụ rồi tiếp tục chạy.
        if any(not isfinite(score) or score < 0 for score in scores):
            raise ValueError(
                "Các fitness score phải hữu hạn và không được âm."
            )

    @property
    def fitness_key(self) -> tuple[float, float, float]:
        """Trả khóa so sánh đúng thứ tự ưu tiên của Gate F.

        Python so sánh tuple từ trái sang phải, vì vậy ``Q_general`` tốt hơn
        không thể bù cho ``Q_time`` kém hơn; tương tự, nguyện vọng giảng viên
        không thể lấn át hai tầng chất lượng đứng trước.
        """

        return (
            self.time_stability_score,
            self.general_quality_score,
            self.lecturer_preference_score,
        )


@dataclass(frozen=True, slots=True)
class OptimizationMetrics:
    """Tổng hợp số liệu của toàn bộ một lần chạy optimizer.

    Các số đếm này dùng chung cho GA, PO và GA–PO để kết quả thực nghiệm có
    thể so sánh trực tiếp. Đặc biệt, ``candidate_attempts`` và
    ``fitness_evaluations`` là hai đại lượng khác nhau: một ứng viên có thể bị
    decoder, repair hoặc validator loại trước khi Fitness được gọi.

    Attributes:
        completed_iterations: Số vòng lặp đã hoàn thành. Giá trị bằng 0 vẫn
            hợp lệ khi lần chạy chỉ mới tạo và đánh giá quần thể ban đầu.
        candidate_attempts: Tổng số ứng viên đã được đưa vào pipeline đánh
            giá, gồm cả giai đoạn khởi tạo và tạo offspring.
        fitness_evaluations: Tổng số lần Fitness thực sự được gọi. Đây là FE
            dùng làm ngân sách so sánh công bằng giữa các optimizer.
        decode_failed_count: Số ứng viên không thể giải mã trong giới hạn tìm
            kiếm của decoder.
        validation_failed_count: Số ứng viên đã giải mã nhưng vẫn vi phạm
            điều kiện bắt buộc sau repair nên bị validator loại.
        repaired_individual_count: Số ứng viên được repair thành công trước
            khi được đánh giá fitness.
        failed_repair_count: Số lần repair được gọi nhưng không tạo được lịch
            chấp nhận được.
        total_repair_attempts: Tổng số lần pipeline gọi repair, bất kể kết quả
            thành công hay thất bại.
        discarded_offspring_count: Số offspring bị bỏ sau khi đã dùng hết số
            lần thử được cấu hình; optimizer phải giữ quần thể cũ thay vì gán
            cho offspring một fitness giả.
        total_decode_nodes: Tổng số nút tìm kiếm decoder đã duyệt.
        total_decode_backtracks: Tổng số lần decoder phải quay lui.
        runtime_seconds: Thời gian chạy theo giây, được đo bằng đồng hồ đơn
            điệu như ``time.perf_counter`` ở lớp điều phối optimizer.

    Class này chỉ là ảnh chụp số liệu sau khi chạy. Nó không tự tăng bộ đếm và
    không chứa logic dừng của GA, PO hoặc GA–PO.
    """

    completed_iterations: int
    candidate_attempts: int
    fitness_evaluations: int
    decode_failed_count: int
    validation_failed_count: int
    repaired_individual_count: int
    failed_repair_count: int
    total_repair_attempts: int
    discarded_offspring_count: int
    total_decode_nodes: int
    total_decode_backtracks: int
    runtime_seconds: float

    def __post_init__(self) -> None:
        """Bảo đảm số liệu tổng hợp không chứa trạng thái bất khả thi."""

        integer_counts = (
            self.completed_iterations,
            self.candidate_attempts,
            self.fitness_evaluations,
            self.decode_failed_count,
            self.validation_failed_count,
            self.repaired_individual_count,
            self.failed_repair_count,
            self.total_repair_attempts,
            self.discarded_offspring_count,
            self.total_decode_nodes,
            self.total_decode_backtracks,
        )

        # Mọi bộ đếm đều biểu diễn số lần một sự kiện đã xảy ra nên không thể
        # âm. Cho phép bằng 0 để biểu diễn các nhánh chưa từng được sử dụng.
        if any(count < 0 for count in integer_counts):
            raise ValueError("Các bộ đếm optimization không được âm.")

        # Fitness chỉ được gọi sau khi một ứng viên đã đi vào pipeline. Vì vậy
        # FE không bao giờ được lớn hơn tổng số ứng viên đã thử.
        if self.fitness_evaluations > self.candidate_attempts:
            raise ValueError(
                "fitness_evaluations không được lớn hơn candidate_attempts."
            )

        # Thời gian âm, NaN hoặc vô cực không thể dùng để so sánh thực nghiệm.
        if not isfinite(self.runtime_seconds) or self.runtime_seconds < 0:
            raise ValueError("runtime_seconds phải hữu hạn và không được âm.")

    @property
    def rejected_candidate_count(self) -> int:
        """Trả tổng số ứng viên bị loại trước bước tính Fitness.

        Hai nhóm loại trừ nhau theo pipeline hiện tại: ứng viên decode thất bại
        dừng ngay tại decoder, còn validation thất bại chỉ được ghi sau khi đã
        có một lịch giải mã được để validator kiểm tra.
        """

        return self.decode_failed_count + self.validation_failed_count


def accumulate_candidate_evaluation(
    metrics: OptimizationMetrics,
    evaluation: CandidateEvaluationResult,
) -> OptimizationMetrics:
    """Cộng số liệu của đúng một lần đánh giá ứng viên vào metrics.

    Args:
        metrics: Ảnh chụp số liệu trước khi vector hiện tại được đánh giá.
        evaluation: Kết quả trả về từ
            :func:`population.evaluate_candidate` cho đúng một vector.

    Returns:
        Một :class:`OptimizationMetrics` mới chứa số liệu đã cộng. Đối tượng
        ``metrics`` đầu vào không bị sửa vì các hợp đồng kết quả của project
        là bất biến.

    Raises:
        ValueError: Nếu ``evaluation`` có trạng thái ``NO_OPTION``. Trạng thái
            này cho biết miền đầu vào bị rỗng hoặc thay đổi sai sau preflight;
            optimizer phải dừng thay vì coi nó là một offspring thông thường.

    Helper này chỉ cộng dữ liệu mà một lần gọi ``evaluate_candidate`` thực sự
    biết được: một candidate attempt, FE, trạng thái lỗi, chi phí repair, node
    và backtrack. Nó không tăng iteration, runtime hoặc
    ``discarded_offspring_count``. Ba số liệu đó thuộc cấp điều phối vòng lặp:
    một offspring chỉ bị xem là đã bỏ sau khi dùng hết nhiều lần thử được cấu
    hình, chứ không phải sau một ``CandidateEvaluationResult`` đơn lẻ.
    """

    # NO_OPTION là lỗi miền đầu vào mang tính kết thúc. Preflight phải phát
    # hiện trạng thái này trước khi optimizer chạy; nếu nó xuất hiện tại đây,
    # việc tiếp tục cộng như một lần decode thất bại sẽ che lỗi dữ liệu.
    if evaluation.status == CandidateEvaluationStatus.NO_OPTION:
        raise ValueError(
            "Không thể cộng NO_OPTION như một lần đánh giá offspring; "
            "optimizer phải dừng vì miền đầu vào không hợp lệ."
        )

    decode_failed_increment = 0
    validation_failed_increment = 0
    if evaluation.status == CandidateEvaluationStatus.DECODE_FAILED:
        decode_failed_increment = 1
    elif evaluation.status == CandidateEvaluationStatus.VALIDATION_FAILED:
        validation_failed_increment = 1

    repaired_individual_increment = 0
    failed_repair_increment = 0
    repair_attempt_increment = 0
    repair_result = evaluation.repair_result

    if repair_result is not None:
        # ``attempts`` đếm số lần repair thực sự gọi lại decoder. Một lần gọi
        # repair có thể thử nhiều gene nên không được chỉ cộng cố định một.
        repair_attempt_increment = repair_result.attempts

        if repair_result.status == RepairStatus.REPAIRED:
            repaired_individual_increment = 1
        elif repair_result.status == RepairStatus.FAILED:
            failed_repair_increment = 1

        # NOT_REPAIRABLE thường có attempts = 0: repair đã xác định không có
        # thay đổi gene nào để thử. Trạng thái này không được tính là một lần
        # repair đã thử rồi thất bại, phù hợp cách khởi tạo quần thể đang đếm.

    # ``replace`` tạo ảnh chụp mới và đồng thời chạy lại validation của
    # OptimizationMetrics. Nhờ đó FE không thể vô tình vượt candidate attempts
    # và mọi bộ đếm tiếp tục được kiểm tra là số không âm.
    return replace(
        metrics,
        candidate_attempts=metrics.candidate_attempts + 1,
        fitness_evaluations=(
            metrics.fitness_evaluations + evaluation.fitness_evaluations
        ),
        decode_failed_count=(
            metrics.decode_failed_count + decode_failed_increment
        ),
        validation_failed_count=(
            metrics.validation_failed_count + validation_failed_increment
        ),
        repaired_individual_count=(
            metrics.repaired_individual_count
            + repaired_individual_increment
        ),
        failed_repair_count=(
            metrics.failed_repair_count + failed_repair_increment
        ),
        total_repair_attempts=(
            metrics.total_repair_attempts + repair_attempt_increment
        ),
        total_decode_nodes=(
            metrics.total_decode_nodes + evaluation.total_decode_nodes
        ),
        total_decode_backtracks=(
            metrics.total_decode_backtracks
            + evaluation.total_decode_backtracks
        ),
    )


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    """Kết quả chuẩn hóa được trả về bởi GA, PO hoặc GA–PO.

    Attributes:
        algorithm: Thuật toán đã tạo ra kết quả.
        best_individual: Cá thể tốt nhất từng được tìm thấy trong toàn bộ run.
        final_population: Quần thể còn lại sau iteration cuối cùng.
        convergence_history: Các mốc nghiệm tốt nhất theo iteration và FE.
        metrics: Toàn bộ số liệu tổng hợp của lần chạy.

    ``best_individual`` không bắt buộc phải nằm trong ``final_population``.
    Một optimizer có thể lưu best toàn cục riêng, trong khi quần thể hiện tại
    đã di chuyển sang những vị trí khác.
    """

    algorithm: OptimizationAlgorithm
    best_individual: TimetableIndividual
    final_population: tuple[TimetableIndividual, ...]
    convergence_history: tuple[ConvergencePoint, ...]
    metrics: OptimizationMetrics

    def __post_init__(self) -> None:
        """Kiểm tra tính nhất quán của kết quả tối ưu."""

        # Một run thành công luôn phải còn ít nhất một cá thể hợp lệ.
        if not self.final_population:
            raise ValueError("final_population không được rỗng.")

        # Lịch sử luôn bắt đầu từ quần thể ban đầu tại iteration 0.
        if not self.convergence_history:
            raise ValueError("convergence_history không được rỗng.")

        first_point = self.convergence_history[0]
        if first_point.iteration != 0:
            raise ValueError(
                "Mốc convergence đầu tiên phải có iteration bằng 0."
            )

        # Các mốc phải đi theo đúng thứ tự thời gian. FE có thể giữ nguyên nếu
        # cả iteration không tạo được offspring hợp lệ, nhưng không được giảm.
        previous_point = first_point
        for current_point in self.convergence_history[1:]:
            if current_point.iteration <= previous_point.iteration:
                raise ValueError(
                    "Iteration trong convergence_history phải tăng dần."
                )

            if (
                current_point.fitness_evaluations
                < previous_point.fitness_evaluations
            ):
                raise ValueError(
                    "Fitness evaluations trong convergence_history "
                    "không được giảm."
                )

            # Đây là lịch sử best-so-far trong bài toán tối thiểu hóa. Nghiệm
            # tốt nhất có thể giữ nguyên hoặc tốt lên, không được xấu đi.
            if current_point.fitness_key > previous_point.fitness_key:
                raise ValueError(
                    "Best fitness trong convergence_history không được xấu đi."
                )

            previous_point = current_point

        last_point = self.convergence_history[-1]

        # Mốc cuối phải mô tả đúng thời điểm mà metrics cho biết run đã dừng.
        if last_point.iteration != self.metrics.completed_iterations:
            raise ValueError(
                "Iteration cuối phải khớp completed_iterations."
            )

        if last_point.fitness_evaluations != self.metrics.fitness_evaluations:
            raise ValueError(
                "FE cuối phải khớp fitness_evaluations trong metrics."
            )

        # Ba score tại điểm hội tụ cuối phải đúng với nghiệm tốt nhất được trả.
        if last_point.fitness_key != self.best_individual.fitness_key:
            raise ValueError(
                "Fitness của mốc cuối phải khớp best_individual."
            )
