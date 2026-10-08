"""Các phép toán nền tảng của Parrot Optimizer V2 cho bài toán thời khóa biểu.

Trong mô hình random-key của project, một cá thể là vector số thực ``X`` có số
chiều bằng số ``ClassSession``. Gene thứ ``d`` không lưu trực tiếp ID của phòng
hoặc ``SessionOption``; nó biểu diễn mức ưu tiên của option cho session tương
ứng. Vì decoder ánh xạ gene trong đoạn ``[0, 1]``, mọi vị trí do PO tạo ra phải
được boundary control trước khi đánh giá.

Module này cài đặt phần toán học tạo vị trí đề xuất và các helper nhỏ dùng để
đưa một vị trí PO qua pipeline đánh giá chung:

``X hiện tại -> một hành vi PO V2 -> X đề xuất -> chặn biên [0, 1]``

Helper offspring chuyển vector đề xuất vào ``population.evaluate_candidate``
và có thể thử lại theo giới hạn đã cấu hình. Decoder, repair, validator và
fitness vẫn là các thành phần chịu trách nhiệm biến vector thành lịch và đánh
giá chất lượng; PO không lặp lại các trách nhiệm đó trong module này. Vòng lặp
``run_po`` điều phối quần thể theo PO V2, lưu best toàn cục riêng và trả kết quả
theo hợp đồng metrics dùng chung với GA và GA–PO.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, replace
from enum import IntEnum
from random import Random
from time import perf_counter
from typing import Sequence

from .metrics import (
    ConvergencePoint,
    OptimizationMetrics,
    OptimizationResult,
    accumulate_candidate_evaluation,
)
from .models import (
    OptimizationAlgorithm,
    ProblemInstance,
    SessionOption,
)
from .population import (
    CandidateEvaluationConfig,
    CandidateEvaluationResult,
    PopulationInitializationResult,
    PopulationInitializationStatus,
    TimetableIndividual,
    best_individual,
    evaluate_candidate,
)


# ``Vector`` biểu diễn một vị trí trong không gian tìm kiếm liên tục của PO.
# Tuple được dùng để phù hợp với ``TimetableIndividual`` bất biến và tránh một
# phép cập nhật vô ý làm thay đổi cá thể cha đang được lưu trong quần thể.
Vector = tuple[float, ...]


class PoBehavior(IntEnum):
    """Mã định danh cho bốn chiến lược cập nhật vị trí của PO V2.

    Giá trị số 1..4 được giữ cùng thứ tự với mã tham chiếu. Vòng lặp PO sẽ bốc
    ngẫu nhiên một giá trị cho mỗi cá thể ở mỗi iteration.
    """

    # Tìm kiếm bằng bước Lévy, sai khác với best và thông tin mean quần thể.
    FORAGING = 1

    # Di chuyển quanh vị trí hiện tại dưới ảnh hưởng của best và nhiễu Gaussian.
    STAYING = 2

    # Trao đổi thông tin với mean quần thể hoặc dịch chuyển bằng hàm mũ.
    COMMUNICATING = 3

    # Điều chỉnh vị trí theo hai thành phần hút về và đẩy khỏi best.
    FEAR_OF_STRANGERS = 4


@dataclass(frozen=True, slots=True)
class PoConfig:
    """Cấu hình kỹ thuật cho một lần chạy PO trên bài toán thời khóa biểu.

    Attributes:
        max_fitness_evaluations: Số lần tối đa mà lần chạy được phép gọi
            Fitness. Những vector thất bại trước Fitness không làm tăng FE.
        max_offspring_attempts: Số vector đề xuất tối đa được thử để tạo một
            cá thể con hợp lệ cho một vị trí trong quần thể.
        seed: Hạt giống của bộ sinh số ngẫu nhiên, dùng để tái lập lần chạy.
        evaluation_config: Giới hạn dùng chung cho Decoder và Repair trong
            ``population.evaluate_candidate``.

    Kích thước quần thể không được lưu tại đây vì ``run_po`` sẽ nhận trực tiếp
    một quần thể ban đầu đã hợp lệ và lấy kích thước bằng ``len(population)``.
    Các kiểm tra phụ thuộc kích thước quần thể sẽ được thực hiện tại đầu vòng
    lặp, không đặt trong lớp cấu hình này.
    """

    max_fitness_evaluations: int
    max_offspring_attempts: int
    seed: int
    evaluation_config: CandidateEvaluationConfig

    def __post_init__(self) -> None:
        """Từ chối các giới hạn không thể tạo một lần chạy hợp lệ."""

        if self.max_fitness_evaluations < 1:
            raise ValueError(
                "max_fitness_evaluations phải lớn hơn hoặc bằng 1."
            )

        if self.max_offspring_attempts < 1:
            raise ValueError(
                "max_offspring_attempts phải lớn hơn hoặc bằng 1."
            )


@dataclass(frozen=True, slots=True)
class PoOffspringResult:
    """Kết quả thử tạo một cá thể con PO cho một vị trí trong quần thể.

    Attributes:
        individual: Cá thể con hợp lệ đầu tiên tìm được, hoặc ``None`` nếu đã
            dùng hết ``max_offspring_attempts``.
        metrics: Ảnh chụp metrics sau khi cộng toàn bộ lần thử và, nếu cần,
            một offspring bị bỏ.
        attempts_used: Số vector PO đã thực sự sinh và đưa vào pipeline.
        last_evaluation: Kết quả đánh giá của vector cuối cùng. Trường này giúp
            truy nguyên nguyên nhân thất bại mà không biến lỗi cá thể thành lỗi
            toàn bộ bài toán.

    Result không quyết định cá thể nào sống sang thế hệ sau. Khi
    ``individual`` là ``None``, vòng lặp PO cấp trên chịu trách nhiệm giữ cá
    thể cha ở vị trí hiện tại để quần thể không bị thiếu.
    """

    individual: TimetableIndividual | None
    metrics: OptimizationMetrics
    attempts_used: int
    last_evaluation: CandidateEvaluationResult

    def __post_init__(self) -> None:
        """Bảo đảm trạng thái trả về thống nhất với evaluation cuối."""

        if self.attempts_used < 1:
            raise ValueError("attempts_used phải lớn hơn hoặc bằng 1.")

        if self.individual is None and self.last_evaluation.is_success:
            raise ValueError(
                "Evaluation thành công phải trả kèm TimetableIndividual."
            )

        if self.individual is not None:
            if not self.last_evaluation.is_success:
                raise ValueError(
                    "Không được trả cá thể con từ evaluation thất bại."
                )
            if self.last_evaluation.individual != self.individual:
                raise ValueError(
                    "Cá thể con phải đúng là individual của evaluation cuối."
                )

    @property
    def is_success(self) -> bool:
        """Cho biết helper đã tạo được một cá thể con hợp lệ hay chưa."""

        return self.individual is not None


def _validate_po_run_inputs(
    problem: ProblemInstance,
    initialization: PopulationInitializationResult,
    config: PoConfig,
) -> int:
    """Kiểm tra đầu vào và tính số iteration của một lần chạy PO.

    Args:
        problem: Snapshot bài toán thời khóa biểu đã khóa.
        initialization: Kết quả tạo quần thể ban đầu bằng
            :func:`population.initialize_population`.
        config: Cấu hình ngân sách và đánh giá của PO.

    Returns:
        Số iteration PO được phép thực hiện sau giai đoạn khởi tạo.

    Raises:
        ValueError: Nếu khởi tạo thất bại, quần thể không đầy đủ, vector sai
            số chiều, gene nằm ngoài miền hoặc ngân sách FE không phù hợp.

    Quần thể ban đầu đã được đánh giá Fitness nên chi phí khởi tạo cũng phải
    nằm trong ngân sách chung. Mỗi iteration có tối đa ``N`` offspring hợp lệ,
    trong đó ``N`` là kích thước quần thể. Vì vậy phần FE còn lại phải chia hết
    cho ``N`` để không tạo một iteration cuối chỉ xử lý một phần quần thể.
    """

    # PO chỉ được bắt đầu sau khi initialize_population() đã tạo đủ số cá thể
    # hợp lệ. NO_OPTION và NO_FEASIBLE_SOLUTION_FOUND phải được xử lý trước.
    if initialization.status != PopulationInitializationStatus.SUCCESS:
        raise ValueError(
            "PO chỉ nhận quần thể có trạng thái khởi tạo SUCCESS."
        )

    population = initialization.individuals
    population_size = len(population)

    # Một quần thể rỗng không có mean, best hoặc cá thể cha để cập nhật.
    if population_size == 0:
        raise ValueError("Quần thể ban đầu của PO không được rỗng.")

    # Kết quả SUCCESS phải có đúng số cá thể mà bước khởi tạo đã yêu cầu.
    if population_size != initialization.requested_population_size:
        raise ValueError(
            "Số cá thể khởi tạo phải bằng requested_population_size."
        )

    # Mỗi cá thể hợp lệ trong quần thể ban đầu đã được Fitness gọi đúng một
    # lần. Do đó số FE khởi tạo phải bằng số cá thể được trả về.
    if initialization.fitness_evaluations != population_size:
        raise ValueError(
            "FE khởi tạo phải bằng số cá thể hợp lệ trong quần thể."
        )

    # Một lần gọi Fitness luôn thuộc về một candidate attempt. Số FE không
    # được lớn hơn tổng số vector đã được đưa vào pipeline đánh giá.
    if initialization.fitness_evaluations > initialization.candidate_attempts:
        raise ValueError(
            "FE khởi tạo không được lớn hơn số candidate attempts."
        )

    for individual_index, individual in enumerate(population):
        vector = individual.vector

        # Số chiều vector phải bằng số ClassSession của ProblemInstance.
        # Mỗi ClassSession tương ứng đúng một gene.
        if len(vector) != problem.dimension:
            raise ValueError(
                "Vector của cá thể "
                f"{individual_index} phải có đúng {problem.dimension} gene."
            )

        for gene_index, gene in enumerate(vector):
            # NaN và vô cực không thể ánh xạ ổn định sang SessionOption.
            if not math.isfinite(gene):
                raise ValueError(
                    "Gene "
                    f"{gene_index} của cá thể {individual_index} "
                    "phải là số hữu hạn."
                )

            # Random-key của project luôn nằm trong đoạn đóng [0, 1].
            if gene < 0.0 or gene > 1.0:
                raise ValueError(
                    "Gene "
                    f"{gene_index} của cá thể {individual_index} "
                    "phải nằm trong [0, 1]."
                )

    remaining_fitness_evaluations = (
        config.max_fitness_evaluations
        - initialization.fitness_evaluations
    )

    # Ngân sách chung phải đủ trả cho chính quần thể ban đầu. Nếu số này âm,
    # nghĩa là khởi tạo đã dùng nhiều FE hơn mức cấu hình cho toàn bộ run.
    if remaining_fitness_evaluations < 0:
        raise ValueError(
            "max_fitness_evaluations không được nhỏ hơn FE khởi tạo."
        )

    # Mỗi iteration xử lý lần lượt toàn bộ N vị trí của quần thể. Không cho
    # phép một iteration cuối chỉ xử lý một phần vì điều đó làm các cá thể
    # không nhận cùng số cơ hội cập nhật.
    if remaining_fitness_evaluations % population_size != 0:
        raise ValueError(
            "Phần FE còn lại phải chia hết cho kích thước quần thể."
        )

    max_iterations = remaining_fitness_evaluations // population_size
    return max_iterations


def _create_convergence_point(
    iteration: int,
    fitness_evaluations: int,
    best_individual: TimetableIndividual,
) -> ConvergencePoint:
    """Tạo một mốc hội tụ từ cá thể tốt nhất hiện tại.

    Args:
        iteration: Vòng lặp vừa hoàn thành. Quần thể ban đầu sử dụng
            ``iteration = 0``.
        fitness_evaluations: Tổng số lần Fitness đã thực sự được gọi tính đến
            thời điểm ghi mốc.
        best_individual: Cá thể tốt nhất từng được tìm thấy đến thời điểm này.

    Returns:
        Mốc hội tụ chứa iteration, FE và ba tầng mục tiêu của thời khóa biểu.

    Helper chỉ sao chép kết quả fitness đã có trong ``best_individual``. Nó
    không gọi lại Fitness, không làm tăng FE và không tự tìm cá thể tốt nhất.
    """

    fitness = best_individual.fitness

    return ConvergencePoint(
        iteration=iteration,
        fitness_evaluations=fitness_evaluations,
        time_stability_score=fitness.time_stability_score,
        general_quality_score=fitness.general_quality_score,
        lecturer_preference_score=fitness.lecturer_preference_score,
    )


def _initial_metrics(
    initialization: PopulationInitializationResult,
) -> OptimizationMetrics:
    """Chuyển toàn bộ số liệu khởi tạo sang metrics dùng chung.

    Quần thể đầu đã đi qua cùng pipeline Decoder → Repair → Validator →
    Fitness nên chi phí của giai đoạn này phải được tính vào kết quả PO. Hàm
    chỉ tạo một ảnh chụp bất biến mới; nó không sửa ``initialization`` và không
    tự cộng thêm một lần đánh giá nào.
    """

    return OptimizationMetrics(
        completed_iterations=0,
        candidate_attempts=initialization.candidate_attempts,
        fitness_evaluations=initialization.fitness_evaluations,
        decode_failed_count=initialization.decode_failed_count,
        validation_failed_count=initialization.validation_failed_count,
        repaired_individual_count=(
            initialization.repaired_individual_count
        ),
        failed_repair_count=initialization.failed_repair_count,
        total_repair_attempts=initialization.total_repair_attempts,
        discarded_offspring_count=0,
        total_decode_nodes=initialization.total_decode_nodes,
        total_decode_backtracks=initialization.total_decode_backtracks,
        runtime_seconds=0.0,
    )


def clip_vector_to_unit_interval(vector: Vector) -> Vector:
    """Chặn từng gene về miền random-key hợp lệ ``[0, 1]``.

    Args:
        vector: Vị trí liên tục vừa được một công thức PO tạo ra.

    Returns:
        Vector mới có cùng số chiều. Giá trị âm được thay bằng ``0.0``, giá trị
        lớn hơn 1 được thay bằng ``1.0`` và giá trị hợp lệ được giữ nguyên.

    Hàm trả tuple mới thay vì sửa đầu vào để bảo toàn tính bất biến của cá thể
    cha. Đây là boundary control; nó không kiểm tra tính hợp lệ của thời khóa
    biểu và không thay thế decoder.
    """

    # Boundary control theo từng chiều d:
    #
    #     x'_d = min(1, max(0, x_d))
    #
    # Các công thức PO có thể tạo số ngoài biên, nhưng decoder chỉ nhận [0, 1].
    clipped_vector: list[float] = []
    for value in vector:
        # Biên dưới của miền random-key.
        if value < 0:
            clipped_vector.append(0.0)

        # Biên trên của miền random-key.
        elif value > 1:
            clipped_vector.append(1.0)

        # Gene vốn đã hợp lệ được sao chép mà không làm thay đổi giá trị.
        else:
            clipped_vector.append(value)

    return tuple(clipped_vector)


def calculate_population_mean(vectors: Sequence[Vector]) -> Vector:
    """Tính vector trung bình theo từng chiều của quần thể hiện tại.

    Với quần thể gồm ``N`` cá thể và ``D`` chiều, phần tử thứ ``d`` của kết quả
    là trung bình của gene thứ ``d`` trên toàn bộ ``N`` cá thể. Đây chính là
    ``X_mean`` được một số hành vi PO dùng để mô tả xu hướng chung của quần thể.

    Args:
        vectors: Các vector thuộc cùng một quần thể và phải có cùng số chiều.

    Returns:
        Vector trung bình có cùng số chiều với từng cá thể.

    Raises:
        ValueError: Nếu quần thể rỗng, vector không có chiều hoặc các vector
            không cùng kích thước.

    Vòng lặp PO phải gọi hàm này một lần ở đầu mỗi iteration, trước khi sinh cá
    thể con. Mean không được thay đổi giữa chừng khi từng cá thể đang được xử lý.
    """

    # Với N cá thể, thành phần thứ d của vector trung bình là:
    #
    #                         N
    #     X_mean[d] = (1/N) * Σ X_i[d]
    #                        i=1
    #
    # Mean của quần thể rỗng không có ý nghĩa và thường báo hiệu lỗi orchestration.
    if not vectors:
        raise ValueError("Quần thể rỗng không tính được")

    # Vector đầu tiên xác định số chiều chuẩn của toàn bộ quần thể.
    dimensions = len(vectors[0])
    if dimensions == 0:
        raise ValueError("vector nghiệm phải có ít nhất 1 chiều")

    # Mỗi ô lưu tổng của một chiều trước khi chia cho kích thước quần thể.
    dimension_sums = [0.0] * dimensions
    for vector in vectors:
        # PO yêu cầu mọi cá thể thuộc cùng một không gian tìm kiếm D chiều.
        if len(vector) != dimensions:
            raise ValueError("Tất cả các vector phải có cùng số chiều")

        for dimension_index in range(dimensions):
            dimension_sums[dimension_index] += vector[dimension_index]

    population_size = len(vectors)
    mean_values: list[float] = []
    for dimension_sum in dimension_sums:
        mean_values.append(dimension_sum / population_size)

    return tuple(mean_values)


def levy_flight(dimensions: int, rng: Random) -> Vector:
    """Sinh vector bước nhảy Lévy bằng thuật toán Mantegna của PO V2.

    Args:
        dimensions: Số chiều của cá thể, bằng số gene cần cập nhật.
        rng: Bộ sinh số ngẫu nhiên của lần chạy. Đối tượng được truyền từ ngoài
            để cùng input và seed có thể tái lập cùng chuỗi bước nhảy.

    Returns:
        Vector Lévy có đúng ``dimensions`` phần tử.

    Raises:
        ValueError: Nếu số chiều nhỏ hơn 1.

    Phân phối Lévy thường tạo bước nhỏ nhưng có xác suất tạo bước rất lớn. Đặc
    tính đuôi dài này giúp PO thỉnh thoảng khám phá vùng xa thay vì chỉ tìm kiếm
    quanh vị trí hiện tại. Tham số ``beta = 1.5`` và công thức ``sigma`` được
    giữ nguyên theo PO V2 tham chiếu, không phải tham số tự điều chỉnh của bài
    toán thời khóa biểu.
    """

    if dimensions < 1:
        raise ValueError("Số chiều của bước Lévy phải lớn hơn hoặc bằng 1.")

    # Beta được giữ bằng 1.5 theo PO V2 tham chiếu.
    beta = 1.5

    # Sigma là hệ số tỉ lệ của tử số u trong thuật toán Mantegna:
    #
    #         Γ(1+β) * sin(πβ/2)
    # σ = [ ------------------------- ]^(1/β)
    #        Γ((1+β)/2) * β * 2^((β-1)/2)
    #
    # Trong đó Γ là hàm Gamma và β = 1.5.
    sigma = (
        math.gamma(1.0 + beta)
        * math.sin(math.pi * beta / 2.0)
        / (
            math.gamma((1.0 + beta) / 2.0)
            * beta
            * 2.0 ** ((beta - 1.0) / 2.0)
        )
    ) ** (1.0 / beta)

    levy_values: list[float] = []
    for _ in range(dimensions):
        # Mỗi chiều d sử dụng một cặp Gaussian độc lập:
        #
        #     u_d = Normal(0, 1) * σ
        #     v_d = Normal(0, 1)
        #
        # Nhân u với sigma tạo đúng phân phối tỉ lệ của thuật toán Mantegna.
        u = rng.gauss(0.0, 1.0) * sigma
        v = rng.gauss(0.0, 1.0)

        # Công thức bước Lévy tại chiều d:
        #
        #     Levy[d] = u_d / |v_d|^(1/β)
        #
        # Khi |v| gần 0, bước nhảy có thể rất lớn;
        # epsilon chỉ ngăn chia cho 0 chứ không loại bỏ cơ chế nhảy xa này.
        denominator = max(
            abs(v) ** (1.0 / beta),
            sys.float_info.epsilon,
        )
        levy_values.append(u / denominator)

    return tuple(levy_values)


def create_po_position(
    current: Vector,
    current_index: int,
    behavior: PoBehavior,
    best_position: Vector,
    population_mean: Vector,
    iteration: int,
    max_iterations: int,
    alpha: float,
    theta: float,
    rng: Random,
) -> Vector:
    """Áp dụng đúng một hành vi PO V2 để tạo vị trí đề xuất.

    Args:
        current: Vị trí của cá thể đang được cập nhật, ký hiệu ``X_i^t``.
        current_index: Chỉ số zero-based của cá thể trong quần thể. Công thức
            giao tiếp đổi thành ``current_index + 1`` khi cần chỉ số one-based
            giống mã tham chiếu.
        behavior: Một trong bốn hành vi của :class:`PoBehavior`.
        best_position: Vị trí tốt nhất đã biết, ký hiệu ``X_best``. Vòng lặp PO
            phải cập nhật best ngay sau một cá thể con tốt hơn để cá thể phía
            sau trong cùng iteration có thể sử dụng best mới.
        population_mean: Mean của quần thể cha tại đầu iteration.
        iteration: Iteration hiện tại, đánh số từ 1.
        max_iterations: Tổng số iteration dùng trong hệ số tiến độ.
        alpha: Hệ số giao tiếp được sinh một lần cho cả iteration bằng
            ``rng.random() / 5``.
        theta: Góc dùng trong hành vi sợ người lạ, được sinh một lần cho cả
            iteration bằng ``rng.random() * pi``.
        rng: Bộ sinh số ngẫu nhiên thuộc lần chạy hiện tại.

    Returns:
        Vector đề xuất chưa chặn biên. Bên gọi phải truyền kết quả qua
        :func:`clip_vector_to_unit_interval` trước khi đánh giá.

    Raises:
        ValueError: Nếu các vector khác số chiều, chỉ số/iteration không hợp lệ
            hoặc mã hành vi không được hỗ trợ.

    Hàm không sửa ``current``, không decode lịch và không tính fitness. Việc
    tách riêng phép toán này cho phép unit test đối chiếu từng công thức với mã
    PO V2 tham chiếu mà không phụ thuộc vào dữ liệu thời khóa biểu.
    """

    # Ba vector tham gia phép tính phải cùng nằm trong không gian D chiều.
    dimensions = len(current)
    if dimensions == 0:
        raise ValueError("vector nghiệm phải có ít nhất 1 chiều")
    if len(best_position) != dimensions:
        raise ValueError("Best vector phải có cùng số chiều với current.")
    if len(population_mean) != dimensions:
        raise ValueError("Mean vector phải có cùng số chiều với current.")
    if current_index < 0:
        raise ValueError("current_index phải lớn hơn hoặc bằng 0.")
    if max_iterations < 1:
        raise ValueError("max_iterations phải lớn hơn hoặc bằng 1.")
    if iteration < 1 or iteration > max_iterations:
        raise ValueError("iteration phải nằm trong khoảng 1..max_iterations.")

    # Ký hiệu dùng chung trong bốn phương trình:
    #
    #     p = t/T          (mức tiến triển của lần chạy)
    #     r = 1 - t/T      (phần tiến trình còn lại)
    #
    # Trong code: t = iteration, T = max_iterations, p = progress và
    # r = remaining_progress. Khi t tăng, p tăng dần đến 1 còn r giảm về 0.
    progress = iteration / max_iterations
    remaining_progress = 1.0 - progress

    if behavior == PoBehavior.FORAGING:
        # Hành vi kiếm ăn kết hợp ba nguồn thông tin:
        # 1) sai khác giữa current và best;
        # 2) bước Lévy riêng theo từng chiều;
        # 3) mean của quần thể với biên độ giảm dần theo iteration.
        # Công thức theo từng chiều, với ⊙ là phép nhân theo từng phần tử:
        #
        # X_i^(t+1) = (X_i^t - X_best) ⊙ Levy(D)
        #               + rand(0,1) * r^(2p) * X_mean
        #
        # Công thức tham chiếu không cộng thêm X_i^t ở đầu biểu thức này.
        levy_step = levy_flight(dimensions, rng)
        random_factor = rng.random()
        mean_factor = random_factor * (remaining_progress ** (2.0 * progress))
        new_position: list[float] = []
        for dimension_index in range(dimensions):
            value = (
                (current[dimension_index] - best_position[dimension_index])
                * levy_step[dimension_index]
                + mean_factor * population_mean[dimension_index]
            )
            new_position.append(value)
        return tuple(new_position)

    if behavior == PoBehavior.STAYING:
        # Hành vi lưu trú giữ current làm nền, sau đó cộng ảnh hưởng của best
        # qua Lévy và một nhiễu Gaussian giảm dần theo tiến trình.
        #
        # X_i^(t+1) = X_i^t + X_best ⊙ Levy(D)
        #               + randn(0,1) * r * 1_D
        #
        # 1_D là vector gồm D số 1, nên cùng một randn scalar được broadcast
        # lên mọi chiều.
        levy_step = levy_flight(dimensions, rng)

        # ``randn() * ones(1, dim)`` trong công thức tham chiếu có nghĩa là một
        # Gaussian scalar duy nhất được cộng giống nhau vào mọi chiều; không
        # sinh một Gaussian độc lập cho từng gene ở hành vi này.
        gaussian_scalar = rng.gauss(0.0, 1.0)
        gaussian_movement = gaussian_scalar * remaining_progress
        new_position = []
        for dimension_index in range(dimensions):
            value = (
                current[dimension_index]
                + best_position[dimension_index]
                * levy_step[dimension_index]
                + gaussian_movement
            )
            new_position.append(value)

        return tuple(new_position)

    if behavior == PoBehavior.COMMUNICATING:
        # Hành vi giao tiếp bốc một trong hai nhánh với xác suất bằng nhau.
        # H ~ Uniform(0,1) quyết định nhánh; α = rand(0,1)/5 được sinh một lần
        # cho toàn bộ iteration.
        if rng.random() < 0.5:
            # Nhánh 1 di chuyển dựa trên độ lệch giữa cá thể và mean quần thể.
            # ``alpha`` nhỏ giới hạn biên độ của quá trình trao đổi thông tin.
            #
            # Nếu H < 0.5:
            #
            #     X_i^(t+1) = X_i^t + α * r * (X_i^t - X_mean)
            new_position = []
            for dimension_index in range(dimensions):
                value = (
                    current[dimension_index]
                    + alpha
                    * remaining_progress
                    * (
                        current[dimension_index]
                        - population_mean[dimension_index]
                    )
                )
                new_position.append(value)
            return tuple(new_position)

        # Nhánh 2 cộng cùng một lượng dịch chuyển lên mọi chiều. Chỉ số cá thể
        # và số ngẫu nhiên trong mẫu số điều khiển tốc độ suy giảm hàm mũ.
        # Với i là chỉ số one-based của cá thể:
        #
        # Nếu H >= 0.5:
        #
        #     X_i^(t+1) = X_i^t
        #                   + α * r * exp[-i / (rand(0,1) * T)] * 1_D
        #
        # ``current_index + 1`` chuyển chỉ số zero-based của Python thành i.
        random_denominator = max(
            rng.random(),
            sys.float_info.epsilon,
        )
        exponential_term = math.exp(
            -(current_index + 1)
            / (random_denominator * max_iterations)
        )
        movement = alpha * remaining_progress * exponential_term
        new_position = []
        for value in current:
            new_position.append(value + movement)

        return tuple(new_position)

    if behavior == PoBehavior.FEAR_OF_STRANGERS:
        # Hành vi sợ người lạ gồm một thành phần hướng về best và một thành
        # phần phụ thuộc khoảng cách current-best. Hai hệ số lượng giác thay đổi
        # theo iteration và theta nhưng công thức vẫn hoạt động từng chiều.
        #
        # X_i^(t+1) = X_i^t
        #   + rand(0,1) * cos(πt/(2T)) * (X_best - X_i^t)
        #   - cos(θ) * p^(2/T) * (X_i^t - X_best)
        #
        # θ = rand(0,1) * π được sinh một lần cho toàn bộ iteration.
        attraction_factor = (
            rng.random()
            * math.cos(math.pi * iteration / (2.0 * max_iterations))
        )
        repulsion_factor = (
            math.cos(theta)
            * progress ** (2.0 / max_iterations)
        )
        new_position = []
        for dimension_index in range(dimensions):
            distance_to_best = (
                best_position[dimension_index] - current[dimension_index]
            )
            distance_from_best = (
                current[dimension_index] - best_position[dimension_index]
            )
            value = (
                current[dimension_index]
                + attraction_factor * distance_to_best
                - repulsion_factor * distance_from_best
            )
            new_position.append(value)
        return tuple(new_position)

    raise ValueError(f"Hành vi PO không được hỗ trợ: {behavior}")


def _create_and_evaluate_po_offspring(
    problem: ProblemInstance,
    option_domains: tuple[tuple[SessionOption, ...], ...],
    current_individual: TimetableIndividual,
    current_index: int,
    behavior: PoBehavior,
    best_individual: TimetableIndividual,
    population_mean: Vector,
    iteration: int,
    max_iterations: int,
    alpha: float,
    theta: float,
    rng: Random,
    config: PoConfig,
    metrics: OptimizationMetrics,
) -> PoOffspringResult:
    """Sinh và đánh giá một cá thể con PO với số lần thử hữu hạn.

    Args:
        problem: Snapshot bất biến của bài toán thời khóa biểu.
        option_domains: Miền ``SessionOption`` cố định theo thứ tự gene.
        current_individual: Cá thể cha tại vị trí đang được cập nhật.
        current_index: Chỉ số zero-based của cá thể trong quần thể.
        behavior: Hành vi PO đã được bốc cho cá thể này trong iteration.
        best_individual: Nghiệm tốt nhất đã biết tại thời điểm xử lý cá thể.
        population_mean: Mean của quần thể cha tại đầu iteration.
        iteration: Iteration hiện tại, đánh số từ 1.
        max_iterations: Tổng số iteration đã suy ra từ ngân sách FE.
        alpha: Hệ số giao tiếp sinh một lần cho iteration.
        theta: Góc sợ người lạ sinh một lần cho iteration.
        rng: Nguồn ngẫu nhiên duy nhất của lần chạy PO.
        config: Giới hạn thử offspring và cấu hình đánh giá dùng chung.
        metrics: Ảnh chụp số liệu trước khi bắt đầu thử cá thể con này.

    Returns:
        :class:`PoOffspringResult` chứa cá thể con hợp lệ đầu tiên, hoặc
        ``individual=None`` nếu mọi lần thử đều thất bại.

    Raises:
        ValueError: Nếu không còn ngân sách để chấp nhận thêm một FE, hoặc nếu
            pipeline trả ``NO_OPTION`` do miền đầu vào không còn hợp lệ.
        RuntimeError: Nếu ``evaluate_candidate`` phá hợp đồng nội bộ bằng cách
            báo ``SUCCESS`` nhưng không trả cá thể.

    Cùng một ``behavior``, ``alpha`` và ``theta`` được giữ trong mọi lần thử
    của cá thể hiện tại để không thay đổi cấu trúc PO gốc. Mỗi lần gọi
    :func:`create_po_position` vẫn tiêu thụ mẫu ngẫu nhiên mới, vì vậy vector
    đề xuất có thể khác nhau. Helper dừng tại cá thể hợp lệ đầu tiên nên một vị
    trí quần thể tạo tối đa một FE; các vector bị loại trước Fitness chỉ tăng
    candidate attempts và chi phí decoder/repair.
    """

    # Nếu FE đã chạm ngân sách thì một vector thành công tiếp theo sẽ làm vượt
    # giới hạn. Vòng lặp cấp trên không được gọi helper trong trạng thái này.
    if metrics.fitness_evaluations >= config.max_fitness_evaluations:
        raise ValueError(
            "Không còn ngân sách Fitness Evaluation để tạo offspring."
        )

    updated_metrics = metrics
    last_evaluation: CandidateEvaluationResult | None = None

    for attempt_number in range(1, config.max_offspring_attempts + 1):
        # Bước 1: áp dụng đúng hành vi PO đã chọn cho cá thể hiện tại. Các mẫu
        # Lévy/Gaussian/Uniform bên trong được lấy tiếp từ cùng rng của run.
        proposed_vector = create_po_position(
            current=current_individual.vector,
            current_index=current_index,
            behavior=behavior,
            best_position=best_individual.vector,
            population_mean=population_mean,
            iteration=iteration,
            max_iterations=max_iterations,
            alpha=alpha,
            theta=theta,
            rng=rng,
        )

        # Bước 2: mọi công thức PO đều có thể sinh gene ngoài [0,1]. Chặn biên
        # trước decoder để giữ đúng hợp đồng random-key của project.
        bounded_vector = clip_vector_to_unit_interval(proposed_vector)

        # Bước 3: dùng cổng đánh giá duy nhất của GA/PO/hybrid. Helper không
        # tự viết lại decoder, repair, validator hoặc fitness.
        evaluation = evaluate_candidate(
            problem,
            option_domains,
            bounded_vector,
            config.evaluation_config,
        )
        last_evaluation = evaluation

        # Bước 4: cộng attempt, FE thực tế, lỗi và chi phí tìm kiếm. Nếu trạng
        # thái là NO_OPTION, hàm dùng chung sẽ phát ValueError để dừng run.
        updated_metrics = accumulate_candidate_evaluation(
            updated_metrics,
            evaluation,
        )

        if evaluation.is_success:
            if evaluation.individual is None:
                raise RuntimeError(
                    "Evaluation SUCCESS nhưng không có individual."
                )

            return PoOffspringResult(
                individual=evaluation.individual,
                metrics=updated_metrics,
                attempts_used=attempt_number,
                last_evaluation=evaluation,
            )

    # Vòng lặp luôn chạy ít nhất một lần vì PoConfig đã yêu cầu giới hạn dương.
    if last_evaluation is None:
        raise RuntimeError("PO không thực hiện lần thử offspring nào.")

    # Chỉ sau khi dùng hết toàn bộ giới hạn mới tính một offspring bị bỏ. Các
    # lần thử lẻ thất bại không được tính thành nhiều offspring bị bỏ.
    updated_metrics = replace(
        updated_metrics,
        discarded_offspring_count=(
            updated_metrics.discarded_offspring_count + 1
        ),
    )

    return PoOffspringResult(
        individual=None,
        metrics=updated_metrics,
        attempts_used=config.max_offspring_attempts,
        last_evaluation=last_evaluation,
    )


def run_po(
    problem: ProblemInstance,
    option_domains: tuple[tuple[SessionOption, ...], ...],
    initialization: PopulationInitializationResult,
    config: PoConfig,
) -> OptimizationResult:
    """Chạy PO V2 từ một quần thể thời khóa biểu đã khởi tạo hợp lệ.

    Mean của quần thể cha được chụp một lần ở đầu mỗi iteration. ``alpha`` và
    ``theta`` cũng được sinh một lần cho iteration, còn từng cá thể bốc riêng
    một trong bốn hành vi PO. Một offspring hợp lệ luôn thay vị trí cha dù có
    fitness xấu hơn; chỉ khi mọi lần thử đều thất bại mới giữ cha để bảo toàn
    kích thước quần thể. Nghiệm tốt nhất toàn cục được lưu riêng và cập nhật
    ngay để cá thể phía sau trong cùng iteration có thể sử dụng best mới.

    Hàm không cài lại Decoder, Repair, Validator hoặc Fitness. Mọi vector đề
    xuất đều được đánh giá qua ``_create_and_evaluate_po_offspring`` và hợp
    đồng chung trong ``population.py``.
    """

    started_at = perf_counter()

    max_iterations = _validate_po_run_inputs(
        problem,
        initialization,
        config,
    )

    # Miền option thuộc về snapshot đầu vào của lần chạy. Cấu trúc sai hoặc
    # miền rỗng phải bị phát hiện trước khi PO bắt đầu tiêu thụ RNG và FE.
    if len(option_domains) != problem.dimension:
        raise ValueError(
            "Số miền option phải bằng số ClassSession."
        )

    for session_index, domain in enumerate(option_domains):
        if not domain:
            raise ValueError(
                "PO không thể chạy khi có ClassSession "
                "không có SessionOption."
            )
        if any(
            option.session_index != session_index
            for option in domain
        ):
            raise ValueError(
                "Option phải nằm trong miền của đúng session_index."
            )

    # Tạo tuple mới để việc thay quần thể cục bộ không sửa kết quả khởi tạo.
    population = tuple(initialization.individuals)
    population_size = len(population)
    best_so_far = best_individual(population)
    metrics = _initial_metrics(initialization)

    # Iteration 0 mô tả quần thể đầu. Helper chỉ sao chép fitness đã có nên
    # việc ghi mốc này không làm tăng FE.
    convergence_history: list[ConvergencePoint] = [
        _create_convergence_point(
            iteration=0,
            fitness_evaluations=metrics.fitness_evaluations,
            best_individual=best_so_far,
        )
    ]

    # Một RNG duy nhất bảo đảm cùng input và seed tái lập được cả lần chạy.
    rng = Random(config.seed)

    for iteration in range(1, max_iterations + 1):
        # X_mean phải được tính từ toàn bộ quần thể cha và giữ cố định trong
        # iteration; không tính lại sau khi từng cá thể con xuất hiện.
        population_mean = calculate_population_mean(
            tuple(
                individual.vector
                for individual in population
            )
        )

        # Hai tham số ngẫu nhiên này thuộc cấp iteration theo PO V2 tham chiếu.
        # Các cá thể trong cùng iteration dùng chung alpha và theta.
        alpha = rng.random() / 5.0
        theta = rng.random() * math.pi

        next_population: list[TimetableIndividual] = []

        for current_index, current_individual in enumerate(population):
            # Mỗi cá thể bốc riêng một trong bốn hành vi PO V2.
            behavior = PoBehavior(
                rng.randint(
                    PoBehavior.FORAGING.value,
                    PoBehavior.FEAR_OF_STRANGERS.value,
                )
            )

            offspring_result = _create_and_evaluate_po_offspring(
                problem=problem,
                option_domains=option_domains,
                current_individual=current_individual,
                current_index=current_index,
                behavior=behavior,
                best_individual=best_so_far,
                population_mean=population_mean,
                iteration=iteration,
                max_iterations=max_iterations,
                alpha=alpha,
                theta=theta,
                rng=rng,
                config=config,
                metrics=metrics,
            )

            # Helper trả một ảnh chụp metrics mới sau toàn bộ lần thử của vị
            # trí hiện tại. Không được bỏ phép gán này vì sẽ làm mất FE và các
            # bộ đếm decode, validation, repair hoặc offspring bị loại.
            metrics = offspring_result.metrics

            if not offspring_result.is_success:
                # Không có con hợp lệ sau toàn bộ số lần thử: giữ cha chỉ để
                # quần thể không bị thiếu phần tử. Đây không phải chọn lọc tham
                # lam dựa trên fitness.
                next_population.append(current_individual)
                continue

            offspring = offspring_result.individual
            if offspring is None:
                raise RuntimeError(
                    "PO báo tạo offspring thành công nhưng không trả "
                    "TimetableIndividual."
                )

            # PO V2 nguyên bản cho con hợp lệ thay vị trí cha ngay cả khi con
            # xấu hơn. Chỉ best toàn cục được bảo vệ riêng ở khối phía dưới.
            next_population.append(offspring)

            # Cập nhật tức thời để cá thể tiếp theo trong cùng iteration được
            # phép sử dụng nghiệm tốt nhất mới vừa tìm thấy.
            if offspring.fitness_key < best_so_far.fitness_key:
                best_so_far = offspring

        population = tuple(next_population)

        # Mỗi vị trí phải tạo con hợp lệ hoặc giữ đúng cha tương ứng, vì vậy PO
        # không được làm thay đổi kích thước quần thể giữa các iteration.
        if len(population) != population_size:
            raise RuntimeError(
                "PO phải giữ nguyên kích thước quần thể."
            )

        metrics = replace(
            metrics,
            completed_iterations=iteration,
        )

        convergence_history.append(
            _create_convergence_point(
                iteration=iteration,
                fitness_evaluations=metrics.fitness_evaluations,
                best_individual=best_so_far,
            )
        )

    final_metrics = replace(
        metrics,
        runtime_seconds=perf_counter() - started_at,
    )

    return OptimizationResult(
        algorithm=OptimizationAlgorithm.PO,
        best_individual=best_so_far,
        final_population=population,
        convergence_history=tuple(convergence_history),
        metrics=final_metrics,
    )
