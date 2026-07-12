import math
import random
import time
from typing import List, Tuple, Optional


class BiometricsSimulator:
    """
    BiometricsSimulator generates highly realistic human behavioral biometrics data,
    including third-degree cubic Bezier mouse movement curves with micro-jitter,
    non-linear speed profiles modeling Fitts's Law, human-like click delays,
    and natural scrolling patterns.
    """

    def __init__(self, random_seed: Optional[int] = None) -> None:
        if random_seed is not None:
            random.seed(random_seed)

    def _cubic_bezier(self, p0: Tuple[float, float], p1: Tuple[float, float], p2: Tuple[float, float], p3: Tuple[float, float], t: float) -> Tuple[float, float]:
        """Calculates a point along a third-degree Bezier curve at parameter t [0, 1]."""
        # B(t) = (1-t)^3 * P0 + 3*(1-t)^2 * t * P1 + 3*(1-t)*t^2 * P2 + t^3 * P3
        mt = 1.0 - t
        mt2 = mt * mt
        mt3 = mt2 * mt
        t2 = t * t
        t3 = t2 * t

        x = mt3 * p0[0] + 3 * mt2 * t * p1[0] + 3 * mt * t2 * p2[0] + t3 * p3[0]
        y = mt3 * p0[1] + 3 * mt2 * t * p1[1] + 3 * mt * t2 * p2[1] + t3 * p3[1]
        
        return x, y

    def _velocity_profile(self, s: float) -> float:
        """
        Maps a linear ratio s [0, 1] to a non-linear parameter t [0, 1]
        modeling human acceleration and deceleration (Fitts's Law).
        Uses a smooth cubic easing function (smoothstep).
        """
        # Smoothstep: f(x) = 3*x^2 - 2*x^3
        return 3 * (s ** 2) - 2 * (s ** 3)

    def generate_mouse_path(
        self,
        start: Tuple[int, int],
        end: Tuple[int, int],
        duration_range: Tuple[float, float] = (0.4, 1.2),
        steps: int = 50,
        deviation_factor: float = 0.25,
        jitter_magnitude: float = 0.6
    ) -> List[Tuple[float, float, float]]:
        """
        Generates a human-like mouse movement path from start to end coordinates.
        Uses a third-degree Bezier curve with randomized control points,
        a velocity profile modeling acceleration/deceleration,
        and micro-jitter simulating muscle micro-tremors.
        
        Returns:
            A list of tuples: (x, y, timestamp_offset_from_start)
        """
        x1, y1 = float(start[0]), float(start[1])
        x4, y4 = float(end[0]), float(end[1])
        
        # Calculate straight line vector and distance
        dx = x4 - x1
        dy = y4 - y1
        distance = math.sqrt(dx*dx + dy*dy)
        
        if distance < 5:
            # If distance is extremely small, return linear path
            return [(x1, y1, 0.0), (x4, y4, 0.1)]

        # Generate human control points P1 and P2 with random perpendicular deviation
        # P1 is around 1/3 and P2 is around 2/3 along the path
        perpendicular_x = -dy
        perpendicular_y = dx
        
        # Random deviation magnitudes
        dev1 = random.uniform(-deviation_factor, deviation_factor) * distance
        dev2 = random.uniform(-deviation_factor, deviation_factor) * distance

        # Base control points coordinates on the line
        p1_base_x = x1 + dx * 0.33
        p1_base_y = y1 + dy * 0.33
        p2_base_x = x1 + dx * 0.66
        p2_base_y = y1 + dy * 0.66

        # Apply perpendicular deviations to get final control points
        p1 = (
            p1_base_x + (perpendicular_x / max(distance, 1.0)) * dev1,
            p1_base_y + (perpendicular_y / max(distance, 1.0)) * dev1
        )
        p2 = (
            p2_base_x + (perpendicular_x / max(distance, 1.0)) * dev2,
            p2_base_y + (perpendicular_y / max(distance, 1.0)) * dev2
        )

        p0 = (x1, y1)
        p3 = (x4, y4)

        path: List[Tuple[float, float, float]] = []
        total_duration = random.uniform(*duration_range)

        # Generate steps along the curve
        for i in range(steps):
            # linear progress ratio
            s = i / (steps - 1)
            
            # ease to non-linear progress to simulate speed changes
            t = self._velocity_profile(s)
            
            # Compute Bezier point
            bx, by = self._cubic_bezier(p0, p1, p2, p3, t)
            
            # Add micro-jitter (human micro-tremor)
            # The tremor is more pronounced in the middle of movement and reduces at endpoints
            tremor_scale = math.sin(s * math.pi) * jitter_magnitude
            jitter_x = random.gauss(0, 1) * tremor_scale
            jitter_y = random.gauss(0, 1) * tremor_scale
            
            x_final = bx + jitter_x
            y_final = by + jitter_y
            
            # Calculate timestamp offset
            time_offset = s * total_duration
            
            path.append((round(x_final, 2), round(y_final, 2), round(time_offset, 4)))

        return path

    def generate_click_delays(self) -> Tuple[float, float, float]:
        """
        Generates realistic human timing delays for mouse click actions.
        Returns:
            A tuple of float delays in seconds:
            (pre_click_delay, hold_duration, post_click_delay)
        """
        # Pre-click: brief hesitation before clicking (100ms to 350ms)
        pre_click = random.uniform(0.1, 0.35)
        
        # Hold: how long the mouse button is physically held down (60ms to 150ms)
        # Lognormal distribution is highly accurate for physiological measurements
        hold_duration = random.lognormvariate(math.log(0.08), 0.25)
        hold_duration = max(min(hold_duration, 0.3), 0.05)  # Clamped to safe range
        
        # Post-click: pause before next move (150ms to 500ms)
        post_click = random.uniform(0.15, 0.5)
        
        return round(pre_click, 4), round(hold_duration, 4), round(post_click, 4)

    def generate_scroll_steps(self, target_distance: int, step_size: int = 120) -> List[Tuple[int, float]]:
        """
        Generates a series of natural scroll increments to cover a target distance.
        Includes scroll acceleration, deceleration, and human pauses.
        
        Returns:
            A list of tuples: (scroll_delta_pixels, pause_delay_seconds)
        """
        if target_distance == 0:
            return []

        direction = 1 if target_distance > 0 else -1
        remaining = abs(target_distance)
        steps: List[Tuple[int, float]] = []

        # Divide into individual human scrolls
        scrolls = []
        while remaining > 0:
            # Human scroll wheel ticks vary slightly (typically around 100-240px per finger stroke)
            stroke_distance = random.choice([step_size, step_size * 2, step_size // 2])
            stroke = min(stroke_distance, remaining)
            scrolls.append(stroke * direction)
            remaining -= stroke

        num_scrolls = len(scrolls)
        for idx, scroll_amt in enumerate(scrolls):
            # Calculate dynamic delays simulating finger movement
            # Acceleration in start/middle, deceleration near the end of scrolling session
            progress_ratio = (idx + 1) / num_scrolls
            
            # Pauses vary (brief tick pauses, longer pauses to 'read' content)
            is_reading_pause = random.random() < 0.15 and idx > 0 and idx < num_scrolls - 1
            
            if is_reading_pause:
                delay = random.uniform(0.8, 2.5)  # Pause to read
            else:
                # Standard delay between finger strokes (80ms to 400ms)
                # Slower at start and end
                speed_modifier = 1.5 - math.sin(progress_ratio * math.pi)
                delay = random.uniform(0.08, 0.25) * speed_modifier

            steps.append((scroll_amt, round(delay, 4)))

        return steps
