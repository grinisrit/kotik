import numpy as np
import numba as nb

from .common import *
from .black_scholes import *
from .vol_surface import *


@nb.experimental.jitclass([("a", nb.float64)])
class A:
    def __init__(self, a: nb.float64):
        self.a = a


@nb.experimental.jitclass([("b", nb.float64)])
class B:
    def __init__(self, b: nb.float64):
        if not (b >= 0):
            raise ValueError("B not >= 0")
        self.b = b


@nb.experimental.jitclass([("rho", nb.float64)])
class Rho:
    def __init__(self, rho: nb.float64):
        if not (rho >= -1 and rho <= 1):
            raise ValueError("Rho not from [-1, 1]")
        self.rho = rho


@nb.experimental.jitclass([("m", nb.float64)])
class M:
    def __init__(self, m: nb.float64):
        self.m = m


@nb.experimental.jitclass([("sigma", nb.float64)])
class Sigma:
    def __init__(self, sigma: nb.float64):
        if not (sigma > 0):
            raise ValueError("Sigma not > 0")
        self.sigma = sigma


@nb.experimental.jitclass(
    [
        ("a", nb.float64),
        ("b", nb.float64),
        ("rho", nb.float64),
        ("m", nb.float64),
        ("sigma", nb.float64),
    ]
)
class SVIRawParams:
    def __init__(self, a: A, b: B, rho: Rho, m: M, sigma: Sigma):
        self.a = a.a
        self.b = b.b
        self.rho = rho.rho
        self.m = m.m
        self.sigma = sigma.sigma

    def array(self) -> nb.float64[:]:
        return np.array([self.a, self.b, self.rho, self.m, self.sigma])


@nb.experimental.jitclass([("v", nb.float64)])
class V:
    def __init__(self, v: nb.float64):
        self.v = v


@nb.experimental.jitclass([("psi", nb.float64)])
class Psi:
    def __init__(self, psi: nb.float64):
        self.psi = psi


@nb.experimental.jitclass([("p", nb.float64)])
class P:
    def __init__(self, p: nb.float64):
        self.p = p


@nb.experimental.jitclass([("c", nb.float64)])
class C:
    def __init__(self, c: nb.float64):
        self.c = c


@nb.experimental.jitclass([("v_tilda", nb.float64)])
class V_tilda:
    def __init__(self, v_tilda: nb.float64):
        self.v_tilda = v_tilda


@nb.experimental.jitclass(
    [
        ("v", nb.float64),
        ("psi", nb.float64),
        ("p", nb.float64),
        ("c", nb.float64),
        ("v_tilda", nb.float64),
    ]
)
class SVIJumpWingParams:
    def __init__(self, v: V, psi: Psi, p: P, c: C, v_tilda: V_tilda):
        self.v = v.v
        self.psi = psi.psi
        self.p = p.p
        self.c = c.c
        self.v_tilda = v_tilda.v_tilda

    def array(self) -> nb.float64[:]:
        return np.array([self.v, self.psi, self.p, self.c, self.v_tilda])


@nb.experimental.jitclass([("w", nb.float64[:])])
class CalibrationWeights:
    def __init__(self, w: nb.float64):
        if not np.all(w >= 0):
            raise ValueError("Weights must be non-negative")
        if not w.sum() > 0:
            raise ValueError("At least one weight must be non-trivial")
        self.w = w


class SVICalc:
    bs_calc: BSCalc

    def __init__(self):
        self.raw_cached_params = np.array([70.0, 1.0, 0.0, 1.0, 1.0])
        self.jump_wing_cached_params = self.raw_cached_params
        self.calibration_error = 0.0
        self.num_iter = 50
        self.tol = 1e-8
        self.strike_lower = 0.1
        self.strike_upper = 10.0
        self.delta_tol = 1e-8
        self.delta_num_iter = 500
        self.delta_grad_eps = 1e-4
        self.bs_calc = BSCalc()

    def update_raw_cached_params(self, params: SVIRawParams):
        self.raw_cached_params = params.array()

    def update_jump_wing_cached_params(self, params: SVIJumpWingParams):
        self.jump_wing_cached_params = params.array()

    def calibrate(
        self, chain: VolSmileChain, calibration_weights: CalibrationWeights
    ) -> SVIRawParams:
        strikes = chain.Ks
        w = calibration_weights.w

        if not strikes.shape == w.shape:
            raise ValueError(
                "Inconsistent data between strikes and calibration weights"
            )

        m_n = len(strikes) - 2

        if not m_n > 0:
            raise ValueError("Need at least 3 points to calibrate SVI")

        weights = w / w.sum()
        forward = chain.f
        time_to_maturity = chain.T
        implied_vols = chain.sigmas

        def clip_params(params):
            eps = 1e-4
            a, b, rho, m, sigma = params[0], params[1], params[2], params[3], params[4]
            b = np_clip(b, eps, 1000000.0)
            rho = np_clip(rho, -1.0 + eps, 1.0 - eps)
            sigma = np_clip(sigma, eps, 1000000.0)
            # TODO: a + b*sigma*sqrt(1 - rho^2) >= 0
            svi_params = np.array([a, b, rho, m, sigma])
            return svi_params

        def get_residuals(params):
            J = np.stack(
                self._jacobian_vol_svi_raw(
                    forward,
                    time_to_maturity,
                    strikes,
                    params,
                )
            )
            iv = self._vol_svi(
                forward,
                time_to_maturity,
                strikes,
                params,
            )
            res = iv - implied_vols
            return res * weights, J @ np.diag(weights)

        def levenberg_marquardt(f, proj, x0):
            x = x0.copy()

            mu = 1e-2
            nu1 = 2.0
            nu2 = 2.0

            res, J = f(x)
            F = res.T @ res

            result_x = x
            result_error = F / m_n

            for i in range(self.num_iter):
                if result_error < self.tol:
                    break
                multipl = J @ J.T
                I = np.diag(np.diag(multipl)) + 1e-5 * np.eye(len(x))
                dx = np.linalg.solve(mu * I + multipl, J @ res)
                x_ = proj(x - dx)
                res_, J_ = f(x_)
                F_ = res_.T @ res_
                if F_ < F:
                    x, F, res, J = x_, F_, res_, J_
                    mu /= nu1
                    result_error = F / m_n
                else:
                    i -= 1
                    mu *= nu2
                    continue
                result_x = x

            return result_x, result_error

        self.raw_cached_params, self.calibration_error = levenberg_marquardt(
            get_residuals, clip_params, self.raw_cached_params
        )

        # self.jump_wing_cached_params = self._get_jump_wing_params(
        #     self.raw_cached_params, time_to_maturity
        # ).array()

        return SVIRawParams(
            A(self.raw_cached_params[0]),
            B(self.raw_cached_params[1]),
            Rho(self.raw_cached_params[2]),
            M(self.raw_cached_params[3]),
            Sigma(self.raw_cached_params[4]),
        )

    def _get_jump_wing_params(
        self, params: SVIRawParams, T: nb.float64
    ) -> SVIJumpWingParams:
        a, b, rho, m, sigma = params.a, params.b, params.rho, params.m, params.sigma
        v = (a + b * (-rho * m + np.sqrt(m**2 + sigma**2))) / T
        w = v * T
        psi = 1 / np.sqrt(w) * b / 2 * (-m / np.sqrt(m**2 + sigma**2) + rho)
        p = b * (1 - rho) / np.sqrt(w)
        c = b * (1 + rho) / np.sqrt(w)
        v_tilda = 1 / T * (a + b * sigma * np.sqrt(1 - rho**2))
        return SVIJumpWingParams(
            V(v),
            Psi(psi),
            P(p),
            C(c),
            V_tilda(v_tilda),
        )

    def implied_vol(
        self, forward: Forward, strike: Strike, params: SVIRawParams
    ) -> ImpliedVol:
        return ImpliedVol(
            self._vol_svi(
                forward.forward_rate().fv,
                forward.T,
                np.array([strike.K]),
                params.array(),
            )[0]
        )

    def implied_vols(
        self, forward: Forward, strikes: Strikes, params: SVIRawParams
    ) -> ImpliedVols:
        return ImpliedVols(
            self._vol_svi(
                forward.forward_rate().fv, forward.T, strikes.data, params.array()
            )
        )

    def premium(
        self,
        forward: Forward,
        strike: Strike,
        option_type: OptionType,
        params: SVIRawParams,
    ) -> Premium:
        sigma = self._vol_svi(
            forward.forward_rate().fv, forward.T, np.array([strike.K]), params.array()
        )[0]
        return self.bs_calc.premium(forward, strike, option_type, ImpliedVol(sigma))

    def premiums(
        self, forward: Forward, strikes: Strikes, params: SVIRawParams
    ) -> Premiums:
        f = forward.forward_rate().fv
        sigmas = self._vol_svi(f, forward.T, strikes.data, params.array())
        Ks = strikes.data
        res = np.zeros_like(sigmas)
        n = len(sigmas)
        for i in range(n):
            K = Ks[i]
            res[i] = self.bs_calc.premium(
                forward, Strike(K), OptionType(K >= f), ImpliedVol(sigmas[i])
            ).pv
        return Premiums(res)

    def vanilla_premium(
        self,
        spot: Spot,
        forward_yield: ForwardYield,
        vanilla: Vanilla,
        params: SVIRawParams,
    ) -> Premium:
        forward = Forward(spot, forward_yield, vanilla.time_to_maturity())
        return Premium(
            vanilla.N
            * self.premium(forward, vanilla.strike(), vanilla.option_type(), params).pv
        )

    def vanillas_premiums(
        self,
        spot: Spot,
        forward_yield: ForwardYield,
        vanillas: Vanillas,
        params: SVIRawParams,
    ) -> Premiums:
        forward = Forward(spot, forward_yield, vanillas.time_to_maturity())
        f = forward.forward_rate().fv
        Ks = vanillas.Ks
        sigmas = self._vol_svi(f, forward.T, Ks, params.array(), params.beta)
        Ns = vanillas.Ns
        res = np.zeros_like(sigmas)
        n = len(sigmas)
        for i in range(n):
            K = Ks[i]
            N = Ns[i]
            is_call = vanillas.is_call[i]
            res[i] = (
                N
                * self.bs_calc.premium(
                    forward, Strike(K), OptionType(is_call), ImpliedVol(sigmas[i])
                ).pv
            )
        return Premiums(res)

    def _total_implied_var_svi(
        self,
        F: nb.float64,
        Ks: nb.float64[:],
        params: nb.float64[:],
    ) -> nb.float64[:]:
        a, b, rho, m, sigma = params[0], params[1], params[2], params[3], params[4]
        k = np.log(Ks / F)
        w = a + b * (rho * (k - m) + np.sqrt((k - m) ** 2 + sigma**2))
        return w

    def _vol_svi(
        self,
        F: nb.float64,
        T: nb.float64,
        Ks: nb.float64[:],
        params: nb.float64[:],
    ) -> nb.float64[:]:
        w = self._total_implied_var_svi(F=F, Ks=Ks, params=params)
        iv = np.sqrt(w / T)
        return iv

    def _jacobian_total_implied_var_svi_raw(
        self,
        F: nb.float64,
        Ks: nb.float64[:],
        params: nb.float64[:],
    ) -> tuple[nb.float64[:]]:
        a, b, rho, m, sigma = params[0], params[1], params[2], params[3], params[4]
        n = len(Ks)
        k = np.log(Ks / F)
        sqrt = np.sqrt(sigma**2 + (k - m) ** 2)
        dda = np.ones(n, dtype=np.float64)
        ddb = rho * (k - m) + sqrt
        ddrho = b * (k - m)
        ddm = b * (-rho + (m - k) / sqrt)
        ddsigma = b * sigma / sqrt
        return dda, ddb, ddrho, ddm, ddsigma

    def _jacobian_vol_svi_raw(
        self,
        F: nb.float64,
        T: nb.float64,
        Ks: nb.float64[:],
        params: nb.float64[:],
    ) -> tuple[nb.float64[:]]:
        # iv = sqrt(w/T)
        # div/da = (dw/da)/(2*sqrt(T*w))
        w = self._total_implied_var_svi(F=F, Ks=Ks, params=params)
        dda, ddb, ddrho, ddm, ddsigma = self._jacobian_total_implied_var_svi_raw(
            F=F, Ks=Ks, params=params
        )
        denominator = 2 * np.sqrt(T * w)
        return (
            dda / denominator,
            ddb / denominator,
            ddrho / denominator,
            ddm / denominator,
            ddsigma / denominator,
        )

    def _dsigma_df(
        self, F: nb.float64, T: nb.float64, K: nb.float64, params: SVIRawParams
    ) -> nb.float64:
        a, b, rho, m, sigma = params.a, params.b, params.rho, params.m, params.sigma
        Ks = np.array([K])
        w = self._total_implied_var_svi(F=F, Ks=Ks, params=params.array())
        denominator = 2 * np.sqrt(T * w)
        k = np.log(K / F)
        sqrt = np.sqrt(sigma**2 + (k - m) ** 2)
        ddf = b * (-rho / F - (k - m) / (F * sqrt))
        return ddf / denominator

    def _d2_sigma_df2(
        self, F: nb.float64, T: nb.float64, K: nb.float64, params: SVIRawParams
    ) -> nb.float64:
        a, b, rho, m, sigma = params.a, params.b, params.rho, params.m, params.sigma
        Ks = np.array([K])
        w = self._total_implied_var_svi(F=F, Ks=Ks, params=params.array())
        denominator = 2 * np.sqrt(T * w)
        k = np.log(K / F)
        sqrt = np.sqrt(sigma**2 + (k - m) ** 2)
        dddff = (
            rho / F**2
            - (k - m) ** 2 / (F**2 * sqrt**3)
            + (k - m) / (F**2 * sqrt)
            + 1 / (F**2 * sqrt)
        )
        dddff = dddff * b
        return dddff / denominator

    def _da_dv_t(
        self, F: nb.float64, T: nb.float64, K: nb.float64, params: SVIJumpWingParams
    ) -> nb.float64:
        _, psi_t, p_t, c_t, _ = (
            params.v,
            params.psi,
            params.p,
            params.c,
            params.v_tilda,
        )
        epsilon = (-2 * p_t / (c_t + p_t) - 4 * psi_t / (c_t + p_t) + 1) ** 2
        numerator = T * np.sqrt(-1 + 1 / epsilon) * np.sqrt(1 - epsilon)
        denominator = (
            2 * p_t / (c_t + p_t)
            - np.sqrt(-1 + 1 / epsilon) * np.sqrt(1 - (1 - 2 * p_t / (c_t + p_t)) ** 2)
            + np.sqrt(1 / epsilon) * np.sign(np.sqrt(-1 + 1 / epsilon))
            - 1
        )

        return numerator / denominator

    def delta(self, forward: Forward, strike: Strike, params: SVIRawParams) -> Delta:
        F = forward.forward_rate().fv
        sigma = self.implied_vol(forward, strike, params)
        vega_bsm = self.bs_calc.vega(forward, strike, sigma).pv
        dsigma_df = self._dsigma_df(F, forward.T, strike.K, params)
        return Delta(vega_bsm * dsigma_df)

    def vanilla_delta(
        self,
        spot: Spot,
        forward_yield: ForwardYield,
        vanilla: Vanilla,
        params: SVIRawParams,
    ) -> Delta:
        forward = Forward(spot, forward_yield, vanilla.time_to_maturity())
        return Delta(vanilla.N * self.delta(forward, vanilla.strike(), params).pv)

    def deltas(
        self, forward: Forward, strikes: Strikes, params: SVIRawParams
    ) -> Deltas:
        Ks = strikes.data
        n = len(Ks)
        deltas = np.zeros_like(Ks)
        for i in range(n):
            deltas[i] = self.delta(forward, Strike(Ks[i]), params).pv

        return Deltas(deltas)

    def gamma(self, forward: Forward, strike: Strike, params: SVIRawParams) -> Gamma:
        F = forward.forward_rate().fv
        sigma = self.implied_vol(forward, strike, params)
        vega_bsm = self.bs_calc.vega(forward, strike, sigma).pv
        vanna_bsm = self.bs_calc.vanna(forward, strike, sigma).pv
        dsigma_df = self._dsigma_df(F, forward.T, strike.K, params)
        d2_sigma_df2 = self._d2_sigma_df2(F, forward.T, strike.K, params)
        return Gamma(vanna_bsm * dsigma_df + vega_bsm * d2_sigma_df2)

    def gammas(
        self, forward: Forward, strikes: Strikes, params: SVIRawParams
    ) -> Gammas:
        Ks = strikes.data
        n = len(Ks)
        gammas = np.zeros_like(Ks)
        for i in range(n):
            gammas[i] = self.gamma(forward, Strike(Ks[i]), params).pv

        return Gammas(gammas)

    def v_t_greek(
        self,
        forward: Forward,
        time_to_maturity: TimeToMaturity,
        strike: Strike,
        params: SVIRawParams,
    ) -> nb.float64:
        F = forward.forward_rate().fv
        T = time_to_maturity.T
        K = strike.K
        sigma = self.implied_vol(forward, strike, params)
        # dC/dv_t = (dC/d sigma) * (d sigma/d a) * (d a/d v_t) = Vega_BSM * (d sigma/d a) * (d a/d v_t)
        vega_bsm = self.bs_calc.vega(forward, strike, sigma).pv
        dsigma_da, _, _, _, _ = self._jacobian_vol_svi_raw(
            F, T, np.array([K]), params.array()
        )
        jump_wing_params = self._get_jump_wing_params(params, T)
        da_dvt = self._da_dv_t(F, T, K, jump_wing_params)
        return vega_bsm * dsigma_da * da_dvt

    def v_t_greeks(
        self,
        forward: Forward,
        time_to_maturity: TimeToMaturity,
        strikes: Strikes,
        params: SVIRawParams,
    ) -> nb.float64[:]:
        Ks = strikes.data
        n = len(Ks)
        vt_greeks = np.zeros_like(Ks)
        for i in range(n):
            vt_greeks[i] = self.v_t_greek(
                forward, time_to_maturity, Strike(Ks[i]), params
            )

        return vt_greeks
