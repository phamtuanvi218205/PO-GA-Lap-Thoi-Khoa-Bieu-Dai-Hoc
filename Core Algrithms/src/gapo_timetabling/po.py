"""Các phép toán nền tảng của Parrot Optimizer V2 cho bài toán thời khóa biểu.

Trong mô hình random-key của project, một cá thể là vector số thực ``X`` có số
chiều bằng số ``ClassSession``. Gene thứ ``d`` không lưu trực tiếp ID của phòng
hoặc ``SessionOption``; nó biểu diễn mức ưu tiên của option cho session tương
ứng. Vì decoder ánh xạ gene trong đoạn ``[0, 1]``, mọi vị trí do PO tạo ra phải
được boundary control trước khi đánh giá.

Module này chỉ cài đặt phần toán học tạo vị trí đề xuất:

``X hiện tại -> một hành vi PO V2 -> X đề xuất -> chặn biên [0, 1]``

Vòng lặp optimizer được bổ sung ở bước sau sẽ chuyển vector đề xuất vào
``population.evaluate_candidate``. Decoder, repair, validator và fitness vẫn là
các thành phần chịu trách nhiệm biến vector thành lịch và đánh giá chất lượng;
PO không lặp lại các trách nhiệm đó trong module này.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from enum import IntEnum
from random import Random
from typing import Sequence

from .population import CandidateEvaluationConfig


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
