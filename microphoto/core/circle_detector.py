"""Автоопределение круглого поля зрения микроскопа.

Идея: поле зрения — большой круг, снаружи которого (почти) черно. Внутри
поля тоже бывают темные участки (скрещенные николи, пустая часть шлифа),
поэтому полагаться только на яркость или только на HoughCircles нельзя.

Алгоритм:
 1. Уменьшенная копия, канал «максимум по RGB» (цветные зерна в скрещенных
    николях тоже считаются светлыми), легкое размытие.
 2. Кандидаты: по порогам яркости (несколько уровней; выпуклая оболочка
    светлой области), HoughCircles, предыдущий подтвержденный круг.
 3. Уточнение каждого кандидата по радиальным профилям: на каждом луче
    ищется самый сильный перепад «светло внутри → темно снаружи»,
    по найденным точкам круг подгоняется робастным МНК (выбросы отбрасываются).
    Лучи с темной внутренней частью просто не дают точек — это и делает
    метод устойчивым к темным участкам внутри поля.
 4. Оценка качества: доля лучей с выраженным краем, темнота снаружи,
    согласованность точек края. Выбирается лучший кандидат.
 5. Финальное уточнение на изображении большего размера.

Если уверенности нет — возвращается разумный круг по центру кадра
(или предыдущий круг), а пользователь поправит его вручную.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import cv2
import numpy as np

from .models import Circle

log = logging.getLogger(__name__)

WORK_SIDE = 800
N_RAYS = 180
CONFIDENT = 0.5


@dataclass
class Detection:
    circle: Circle
    confidence: float           # 0 … 1
    confident: bool
    method: str = ""


# ------------------------------------------------------------------ утилиты

def _value_channel(rgb: np.ndarray) -> np.ndarray:
    if rgb.ndim == 2:
        return rgb.astype(np.float32)
    return rgb[..., :3].max(axis=2).astype(np.float32)


def fit_circle(xs: np.ndarray, ys: np.ndarray) -> tuple[float, float, float] | None:
    """Алгебраическая подгонка окружности (Kåsa)."""
    if len(xs) < 3:
        return None
    a = np.column_stack([xs, ys, np.ones_like(xs)])
    b = xs * xs + ys * ys
    try:
        sol, *_ = np.linalg.lstsq(a, b, rcond=None)
    except np.linalg.LinAlgError:
        return None
    cx, cy = sol[0] / 2, sol[1] / 2
    r2 = sol[2] + cx * cx + cy * cy
    if not np.isfinite(r2) or r2 <= 0:
        return None
    return float(cx), float(cy), float(math.sqrt(r2))


def robust_fit(xs: np.ndarray, ys: np.ndarray, weights: np.ndarray | None = None,
               iterations: int = 4) -> tuple[tuple[float, float, float], np.ndarray] | None:
    """Подгонка с отбрасыванием выбросов по медианному отклонению."""
    keep = np.ones(len(xs), bool)
    res = None
    for _ in range(iterations):
        if keep.sum() < 8:
            return None
        if weights is not None:
            w = np.sqrt(np.clip(weights[keep], 1e-6, None))
            a = np.column_stack([xs[keep], ys[keep], np.ones(keep.sum())]) * w[:, None]
            b = (xs[keep] ** 2 + ys[keep] ** 2) * w
            try:
                sol, *_ = np.linalg.lstsq(a, b, rcond=None)
            except np.linalg.LinAlgError:
                return None
            cx, cy = sol[0] / 2, sol[1] / 2
            r2 = sol[2] + cx * cx + cy * cy
            if not np.isfinite(r2) or r2 <= 0:
                return None
            res = (float(cx), float(cy), float(math.sqrt(r2)))
        else:
            res = fit_circle(xs[keep], ys[keep])
            if res is None:
                return None
        d = np.abs(np.hypot(xs - res[0], ys - res[1]) - res[2])
        mad = np.median(d[keep]) + 1e-6
        new_keep = d < max(2.5 * 1.4826 * mad, 1.0)
        if np.array_equal(new_keep, keep):
            break
        keep = new_keep
    return (res, keep) if res is not None else None


def _weighted_fit(xs, ys, w):
    sw = np.sqrt(np.clip(w, 1e-9, None))
    a = np.column_stack([xs, ys, np.ones_like(xs)]) * sw[:, None]
    b = (xs * xs + ys * ys) * sw
    try:
        sol, *_ = np.linalg.lstsq(a, b, rcond=None)
    except np.linalg.LinAlgError:
        return None
    cx, cy = sol[0] / 2, sol[1] / 2
    r2 = sol[2] + cx * cx + cy * cy
    if not np.isfinite(r2) or r2 <= 0:
        return None
    return float(cx), float(cy), float(math.sqrt(r2))


def _outermost_drop(drop: np.ndarray, thr: float) -> np.ndarray:
    """Для каждого луча — индекс самого внешнего выраженного перепада.

    Край поля зрения — последний (самый дальний от центра) сильный перепад
    «светло → темно»; более ранние перепады — это границы зерен внутри поля.
    """
    n, m = drop.shape
    peak = drop.max(axis=1)
    strong = (drop >= 0.5 * peak[:, None]) & (drop > thr)
    out = np.argmax(drop, axis=1)
    rows = np.nonzero(strong.any(axis=1))[0]
    for i in rows:
        idx = np.nonzero(strong[i])[0]
        last = idx[-1]
        k = last
        while k - 1 >= 0 and strong[i, k - 1]:
            k -= 1
        out[i] = k + int(np.argmax(drop[i, k:last + 1]))
    return out


def ransac_envelope(xs: np.ndarray, ys: np.ndarray, w: np.ndarray, guess: tuple[float, float, float],
                    iterations: int = 400) -> tuple[float, float, float] | None:
    """RANSAC с асимметричной оценкой: точки на окружности — «за», точки
    заметно снаружи — «против», точки внутри (границы зерен) — нейтральны."""
    n = len(xs)
    if n < 8:
        return None
    rng = np.random.default_rng(12345)
    r0 = guess[2]
    tol = max(1.5, 0.01 * r0)
    ii = rng.integers(0, n, size=(iterations, 3))
    ii = ii[(ii[:, 0] != ii[:, 1]) & (ii[:, 1] != ii[:, 2]) & (ii[:, 0] != ii[:, 2])]
    # описанные окружности всех троек сразу
    ax, ay = xs[ii[:, 0]], ys[ii[:, 0]]
    bx, by = xs[ii[:, 1]], ys[ii[:, 1]]
    qx, qy = xs[ii[:, 2]], ys[ii[:, 2]]
    dd = 2 * (ax * (by - qy) + bx * (qy - ay) + qx * (ay - by))
    good = np.abs(dd) > 1e-9
    dd = np.where(good, dd, 1.0)
    a2, b2, q2 = ax * ax + ay * ay, bx * bx + by * by, qx * qx + qy * qy
    ux = (a2 * (by - qy) + b2 * (qy - ay) + q2 * (ay - by)) / dd
    uy = (a2 * (qx - bx) + b2 * (ax - qx) + q2 * (bx - ax)) / dd
    ur = np.hypot(ax - ux, ay - uy)
    good &= (ur > 0.6 * r0) & (ur < 1.5 * r0) & (np.hypot(ux - guess[0], uy - guess[1]) < 0.5 * r0)
    if not good.any():
        return None
    ux, uy, ur = ux[good], uy[good], ur[good]
    e = np.hypot(xs[None, :] - ux[:, None], ys[None, :] - uy[:, None]) - ur[:, None]
    score = (w[None, :] * (np.abs(e) < tol)).sum(axis=1) - 2.0 * (w[None, :] * (e > 3 * tol)).sum(axis=1)
    k = int(np.argmax(score))
    best = (float(ux[k]), float(uy[k]), float(ur[k]))
    if best is None:
        return None
    e = np.hypot(xs - best[0], ys - best[1]) - best[2]
    inl = np.abs(e) < tol
    if inl.sum() < 6:
        return best
    refit = _weighted_fit(xs[inl], ys[inl], w[inl])
    return refit or best


def envelope_fit(xs: np.ndarray, ys: np.ndarray, w: np.ndarray, start: tuple[float, float, float],
                 iterations: int = 6) -> tuple[float, float, float] | None:
    """Подгонка «по внешней огибающей».

    Настоящий край поля зрения — самые внешние точки перепада. Ложные точки
    (границы темных зерен внутри поля) всегда лежат внутри круга, поэтому
    точки внутри получают малый вес, а точки на окружности и снаружи — полный.
    """
    c = start
    for _ in range(iterations):
        e = np.hypot(xs - c[0], ys - c[1]) - c[2]
        tol = max(1.5, 0.008 * c[2])
        ww = np.where(e >= -tol, 1.0, np.exp(-(((e + tol) / tol) ** 2)))
        # слишком далекие наружу точки (блики) — тоже выбросы
        ww = np.where(e > 10 * tol, 0.0, ww)
        if (ww > 0.5).sum() < 8:
            return None
        nc = _weighted_fit(xs, ys, w * ww)
        if nc is None:
            return None
        if abs(nc[0] - c[0]) + abs(nc[1] - c[1]) + abs(nc[2] - c[2]) < 0.05:
            return nc
        c = nc
    return c


class _Analyzer:
    """Работа с одним (уменьшенным) изображением."""

    def __init__(self, value: np.ndarray) -> None:
        self.v = value
        self.h, self.w = value.shape
        flat = value.ravel()
        self.p02 = float(np.percentile(flat, 2))
        self.p50 = float(np.percentile(flat, 50))
        self.p98 = float(np.percentile(flat, 98))
        self.dyn = max(self.p98 - self.p02, 1.0)
        # Уровень «черноты»: темный хвост гистограммы
        self.dark_thr = self.p02 + max(6.0, 0.08 * self.dyn)
        # Светлые пиксели (прореженные) — круг должен охватывать их все
        lit_thr = self.dark_thr + 0.1 * self.dyn
        step = max(1, int(math.sqrt(self.w * self.h / 40000)))
        sub = value[::step, ::step]
        ys, xs = np.nonzero(sub > lit_thr)
        self.lit_x = xs.astype(np.float32) * step
        self.lit_y = ys.astype(np.float32) * step

    # --- выборка по лучам -------------------------------------------------
    def _rays(self, cx: float, cy: float, radii: np.ndarray, n: int = N_RAYS) -> np.ndarray:
        ang = np.linspace(0, 2 * np.pi, n, endpoint=False, dtype=np.float32)
        ca, sa = np.cos(ang)[:, None], np.sin(ang)[:, None]
        mx = (cx + ca * radii[None, :]).astype(np.float32)
        my = (cy + sa * radii[None, :]).astype(np.float32)
        out = cv2.remap(self.v, mx, my, interpolation=cv2.INTER_LINEAR,
                        borderMode=cv2.BORDER_CONSTANT, borderValue=-1.0)
        return out

    # --- уточнение по радиальным перепадам -------------------------------
    def refine(self, c: tuple[float, float, float], band: float = 0.22, steps: int = 3
               ) -> tuple[float, float, float] | None:
        cx, cy, r = c
        for i in range(steps):
            b = band / (2.2 ** i)
            r0, r1 = r * (1 - b), r * (1 + b)
            m = max(12, int(r1 - r0))
            radii = np.linspace(r0, r1, m, dtype=np.float32)
            prof = self._rays(cx, cy, radii)
            valid = prof >= 0
            p = np.where(valid, prof, np.nan)
            # производная вдоль луча (наружу); край = максимум падения яркости
            d = p[:, 2:] - p[:, :-2]
            d = np.where(np.isnan(d), 0, d)
            thr = max(4.0, 0.06 * self.dyn)
            j = _outermost_drop(-d, thr)
            strength = -d[np.arange(len(j)), j]
            ok = strength > thr
            # снаружи от края должно быть темно
            outer_idx = np.clip(j + 2 + max(2, m // 12), 0, m - 1)
            outer = prof[np.arange(len(j)), outer_idx]
            ok &= (outer >= 0) & (outer < self.dark_thr + 0.25 * self.dyn)
            if ok.sum() < 12:
                return None
            rr = radii[j + 1]
            ang = np.linspace(0, 2 * np.pi, prof.shape[0], endpoint=False)
            xs = cx + np.cos(ang) * rr
            ys = cy + np.sin(ang) * rr
            px, py = xs[ok].astype(np.float64), ys[ok].astype(np.float64)
            pw = strength[ok].astype(np.float64)
            start = ransac_envelope(px, py, pw, (cx, cy, r))
            if start is None:
                fit = robust_fit(px, py, weights=pw)
                if fit is None:
                    return None
                start = fit[0]
            ncx, ncy, nr = start
            env = envelope_fit(px, py, pw, (ncx, ncy, nr))
            if env is not None:
                ncx, ncy, nr = env
            if nr < 0.08 * min(self.w, self.h) or nr > 1.5 * max(self.w, self.h):
                return None
            cx, cy, r = ncx, ncy, nr
        return cx, cy, r

    # --- оценка кандидата -------------------------------------------------
    def score(self, c: tuple[float, float, float]) -> float:
        cx, cy, r = c
        if r < 0.1 * min(self.w, self.h):
            return 0.0
        inner = self._rays(cx, cy, np.array([r * 0.90, r * 0.94, r * 0.97], np.float32))
        outer = self._rays(cx, cy, np.array([r * 1.03, r * 1.06, r * 1.10], np.float32))
        vin = np.where((inner >= 0).all(axis=1), inner.mean(axis=1), np.nan)
        vout = np.where((outer >= 0).all(axis=1), outer.mean(axis=1), np.nan)
        both = ~np.isnan(vin) & ~np.isnan(vout)
        n_valid = int(both.sum())
        if n_valid < N_RAYS * 0.2:
            return 0.0
        contrast = (vin - vout)[both]
        edge = contrast > max(6.0, 0.12 * self.dyn)
        edge_frac = float(edge.mean())
        out_valid = ~np.isnan(vout)
        dark_out = float((vout[out_valid] < self.dark_thr + 0.1 * self.dyn).mean())
        # Внутри не должно быть «сплошной черноты» — иначе это не поле зрения
        in_valid = ~np.isnan(vin)
        lit_in = float((vin[in_valid] > self.dark_thr).mean()) if in_valid.any() else 0.0
        coverage = n_valid / N_RAYS
        # Чем больше видно окружности, тем надежнее
        cov_w = 0.6 + 0.4 * coverage
        # Светлое снаружи круга — признак слишком маленького или смещенного круга
        if len(self.lit_x):
            d2 = (self.lit_x - cx) ** 2 + (self.lit_y - cy) ** 2
            lit_outside = float((d2 > (r * 1.02) ** 2).mean())
        else:
            lit_outside = 0.0
        enclose = max(0.0, 1.0 - 4.0 * lit_outside)
        s = (0.45 * edge_frac + 0.2 * dark_out + 0.1 * lit_in + 0.25 * enclose) * cov_w
        # Круг не может целиком лежать в черноте
        if lit_in < 0.15:
            s *= 0.3
        return float(s)

    # --- кандидаты --------------------------------------------------------
    def mask_candidates(self) -> list[tuple[float, float, float]]:
        out = []
        v8 = np.clip(self.v, 0, 255).astype(np.uint8)
        otsu, _ = cv2.threshold(v8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        thresholds = {
            float(otsu),
            self.dark_thr,
            self.p02 + 0.15 * self.dyn,
            self.p02 + 0.30 * self.dyn,
        }
        k = max(3, int(min(self.w, self.h) * 0.01) | 1)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        big_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k * 3, k * 3))
        for t in sorted(thresholds):
            mask = (self.v > t).astype(np.uint8) * 255
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, big_kernel)
            n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
            if n <= 1:
                continue
            areas = stats[1:, cv2.CC_STAT_AREA]
            largest = int(areas.max())
            if largest < 0.01 * self.w * self.h:
                continue
            # Все заметные светлые области (в скрещенных николях поле
            # распадается на отдельные зерна) — объединяем.
            keep_ids = 1 + np.nonzero(areas >= max(0.002 * self.w * self.h, 0.02 * largest))[0]
            comp = np.isin(labels, keep_ids).astype(np.uint8)
            if comp.sum() < 0.03 * self.w * self.h:
                continue
            contours, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            if not contours:
                continue
            cnt = np.concatenate(contours, axis=0)
            hull = cv2.convexHull(cnt)
            pts = cnt[:, 0, :].astype(np.float64)
            # точки контура, лежащие на выпуклой оболочке и не на краю кадра
            dist = np.array([cv2.pointPolygonTest(hull, (float(x), float(y)), True) for x, y in pts])
            on_hull = np.abs(dist) < 2.0
            inner = (pts[:, 0] > 2) & (pts[:, 0] < self.w - 3) & (pts[:, 1] > 2) & (pts[:, 1] < self.h - 3)
            sel = on_hull & inner
            if sel.sum() >= 20:
                fit = robust_fit(pts[sel, 0], pts[sel, 1])
                if fit is not None:
                    out.append(fit[0])
            if inner.all():
                (mx, my), mr = cv2.minEnclosingCircle(cnt)
                out.append((float(mx), float(my), float(mr)))
            # круг равной площади (заполненная оболочка)
            hull_area = cv2.contourArea(hull)
            m = cv2.moments(hull)
            if m["m00"] > 0:
                out.append((m["m10"] / m["m00"], m["m01"] / m["m00"], math.sqrt(hull_area / math.pi)))
        return out

    def hough_candidates(self) -> list[tuple[float, float, float]]:
        v8 = np.clip(self.v, 0, 255).astype(np.uint8)
        mn = min(self.w, self.h)
        try:
            circles = cv2.HoughCircles(
                v8, cv2.HOUGH_GRADIENT, dp=2, minDist=mn * 0.2,
                param1=60, param2=40,
                minRadius=int(mn * 0.2), maxRadius=int(max(self.w, self.h) * 0.75),
            )
        except cv2.error:
            return []
        if circles is None:
            return []
        return [(float(x), float(y), float(r)) for x, y, r in circles[0][:6]]


def _dedupe(cands: list[tuple[float, float, float]], tol: float) -> list[tuple[float, float, float]]:
    out: list[tuple[float, float, float]] = []
    for c in cands:
        if any(abs(c[0] - o[0]) < tol and abs(c[1] - o[1]) < tol and abs(c[2] - o[2]) < tol for o in out):
            continue
        out.append(c)
    return out


def detect_circle(rgb: np.ndarray, prior: Circle | None = None) -> Detection:
    """Ищет поле зрения на изображении (координаты — в пикселях этого изображения).

    prior — круг с предыдущего подтвержденного кадра (в тех же координатах).
    """
    H, W = rgb.shape[:2]
    default = Circle(W / 2, H / 2, min(W, H) * 0.45)
    try:
        return _detect(rgb, prior, default)
    except Exception:
        log.exception("Ошибка автоопределения круга")
        return Detection(prior or default, 0.0, False, "error")


def _detect(rgb: np.ndarray, prior: Circle | None, default: Circle) -> Detection:
    H, W = rgb.shape[:2]
    k = min(1.0, WORK_SIDE / max(H, W))
    value_full = _value_channel(rgb)
    if k < 1.0:
        small = cv2.resize(value_full, (max(1, round(W * k)), max(1, round(H * k))), interpolation=cv2.INTER_AREA)
    else:
        small = value_full
    small = cv2.GaussianBlur(small, (0, 0), 1.2)
    an = _Analyzer(small)

    if an.dyn < 8:   # почти однотонный кадр
        c = prior or default
        return Detection(c, 0.0, False, "flat")

    cands: list[tuple[float, float, float]] = []
    cands += an.mask_candidates()
    cands += an.hough_candidates()
    prior_s = None
    if prior is not None:
        prior_s = (prior.x * k, prior.y * k, prior.r * k)
        cands.append(prior_s)
    cands.append((default.x * k, default.y * k, default.r * k))
    cands = _dedupe(cands, tol=max(2.0, 0.01 * max(an.w, an.h)))

    scored: list[tuple[float, tuple[float, float, float], str]] = []
    for c in cands:
        refined = an.refine(c)
        for cc, tag in ((refined, "refined"), (c, "raw")):
            if cc is None:
                continue
            s = an.score(cc)
            if prior_s is not None:
                dc = math.hypot(cc[0] - prior_s[0], cc[1] - prior_s[1]) / prior_s[2]
                dr = abs(cc[2] - prior_s[2]) / prior_s[2]
                if dc < 0.05 and dr < 0.05:
                    s += 0.08 * (1 - max(dc, dr) / 0.05)
            scored.append((s, cc, tag))
    if not scored:
        return Detection(prior or default, 0.0, False, "none")
    scored.sort(key=lambda t: t[0], reverse=True)
    best_s, best, tag = scored[0]

    # Финальное уточнение на полном разрешении входного изображения
    if k < 1.0:
        full_v = cv2.GaussianBlur(value_full, (0, 0), 1.2 / max(k, 1e-3) * 0.5)
        an_full = _Analyzer(full_v)
        guess = (best[0] / k, best[1] / k, best[2] / k)
        fine = an_full.refine(guess, band=0.04, steps=2)
        result = fine if fine is not None and abs(fine[2] - guess[2]) < 0.05 * guess[2] else guess
    else:
        result = best

    confidence = float(max(0.0, min(1.0, best_s)))
    circle = Circle(*result)
    if confidence < CONFIDENT * 0.7:
        # Неуверенно: возвращаем запасной вариант, но с найденным, если он не хуже
        fallback = prior or default
        return Detection(fallback if confidence < 0.2 else circle, confidence, False, tag)
    return Detection(circle, confidence, confidence >= CONFIDENT, tag)
