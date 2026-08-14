import math

import numpy as np


SEED = 42
POPULATION_SIZE = 30
DIMENSIONS = 5
MAX_ITERATIONS = 100
LOWER_BOUND = -10.0
UPPER_BOUND = 10.0


def objective_function(position):
    """Sphere benchmark with global minimum f(0, ..., 0) = 0."""
    return np.sum(position**2)


def levy_flight(dimensions, random_generator):
    """Generate a Levy-flight vector using Mantegna's method."""
    beta = 1.5
    sigma = (
        math.gamma(1 + beta)
        * math.sin(math.pi * beta / 2)
        / (
            math.gamma((1 + beta) / 2)
            * beta
            * 2 ** ((beta - 1) / 2)
        )
    ) ** (1 / beta)
    u = random_generator.standard_normal(dimensions) * sigma
    v = random_generator.standard_normal(dimensions)
    return u / (np.abs(v) ** (1 / beta))


def run_parrot_optimizer():
    """Run the continuous Parrot Optimizer V2 on Sphere."""
    rng = np.random.default_rng(SEED)
    population = LOWER_BOUND + rng.random(
        (POPULATION_SIZE, DIMENSIONS)
    ) * (UPPER_BOUND - LOWER_BOUND)
    fitness = np.apply_along_axis(objective_function, 1, population)

    best_index = int(np.argmin(fitness))
    best_position = population[best_index].copy()
    best_fitness = float(fitness[best_index])
    history = [best_fitness]
    print(f"Initial best fitness: {best_fitness:.10f}")

    for iteration in range(1, MAX_ITERATIONS + 1):
        population_mean = np.mean(population, axis=0)
        alpha = rng.random() / 5
        theta = rng.random() * math.pi
        next_population = np.empty_like(population)

        for index in range(POPULATION_SIZE):
            current = population[index]
            strategy = int(rng.integers(1, 5))

            if strategy == 1:
                # Foraging behavior.
                next_position = (
                    (current - best_position)
                    * levy_flight(DIMENSIONS, rng)
                    + rng.random()
                    * (1 - iteration / MAX_ITERATIONS)
                    ** (2 * iteration / MAX_ITERATIONS)
                    * population_mean
                )
            elif strategy == 2:
                # Staying behavior in the corrected V2 implementation.
                next_position = (
                    current
                    + best_position * levy_flight(DIMENSIONS, rng)
                    + rng.standard_normal()
                    * (1 - iteration / MAX_ITERATIONS)
                    * np.ones(DIMENSIONS)
                )
            elif strategy == 3:
                # Communication behavior.
                if rng.random() <= 0.5:
                    next_position = (
                        current
                        + alpha
                        * (1 - iteration / MAX_ITERATIONS)
                        * (current - population_mean)
                    )
                else:
                    denominator = (
                        max(rng.random(), np.finfo(float).eps)
                        * MAX_ITERATIONS
                    )
                    next_position = (
                        current
                        + alpha
                        * (1 - iteration / MAX_ITERATIONS)
                        * math.exp(-(index + 1) / denominator)
                    )
            else:
                # Fear-of-strangers behavior.
                next_position = (
                    current
                    + rng.random()
                    * math.cos(
                        math.pi * iteration / (2 * MAX_ITERATIONS)
                    )
                    * (best_position - current)
                    - math.cos(theta)
                    * (iteration / MAX_ITERATIONS)
                    ** (2 / MAX_ITERATIONS)
                    * (current - best_position)
                )

            next_population[index] = np.clip(
                next_position, LOWER_BOUND, UPPER_BOUND
            )

        next_fitness = np.apply_along_axis(
            objective_function, 1, next_population
        )
        generation_best = int(np.argmin(next_fitness))
        if next_fitness[generation_best] < best_fitness:
            best_fitness = float(next_fitness[generation_best])
            best_position = next_population[generation_best].copy()

        population = next_population
        fitness = next_fitness
        history.append(best_fitness)

        if iteration % 20 == 0:
            print(
                f"Iteration {iteration:3d} | "
                f"best fitness: {best_fitness:.10f}"
            )

    return best_position, best_fitness, history


if __name__ == "__main__":
    position, fitness_value, convergence = run_parrot_optimizer()
    print("-" * 50)
    print(f"Final best fitness: {fitness_value:.12f}")
    print(f"Best position: {position}")
    print(f"Recorded convergence points: {len(convergence)}")
