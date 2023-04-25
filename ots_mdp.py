# -*- coding: utf-8 -*-
"""OTS.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1RWVeMRZ9U4ctivbO-7i3Xh4P-mhd4cd8

# Code for Optimistic Thompson's Sampling for MDP
"""
import os
import json
import copy
import numpy as np
import matplotlib.pyplot as plt
import numba as nb
from tqdm import tqdm
from argparse import ArgumentParser
from multiprocessing import Pool

N_ALGORITHMS = 5

"""# Environment / Util"""

class MDP():
    def __init__(self, S, A, H):
        self.S = S
        self.A = A
        self.H = H
        self.P = np.random.dirichlet(np.ones(S) * 0.1, (S, A, H))
        self.R = np.random.random_sample((S, A, H))
        self.R[np.random.random_sample((S, A, H)) <= 0.85] = 0  # To keep reward sparse
        self.curr_s = np.random.choice(S)
        self.total_reward = 0  # Cumulative reward within one episode

        # Observation statistics
        self.emperical_rewards = np.zeros((S, A, H))
        self.observations = np.ones((S, A, H))
        self.empirical_transition = np.zeros((S, A, H, S))
        self.history = np.zeros((S, A, H, S))  # record the total reward gained by doing (s,a,t) -> s'

    def step(self, a, t):
        s = self.curr_s
        r = self.R[s, a, t]
        next_s = np.random.choice(self.S, p=self.P[self.curr_s, a, t])
        self.update_stats(s, a, t, next_s, r)
        self.curr_s = next_s
        self.total_reward = self.total_reward + r

    def update_stats(self, s, a, t, next_s, r):
        # empirical reward is now a randome bernulli
        emperical_r = np.random.binomial(1, r)
        self.emperical_rewards[s, a, t] += emperical_r
        self.observations[s, a, t] += 1
        self.empirical_transition[s, a, t, next_s] += 1
        self.history[s, a, t, next_s] += emperical_r

    def reset(self):  # reset statistics at the end of each episode
        self.curr_s = np.random.choice(self.S)
        self.total_reward = 0

    def run_fixed_policy(self, p):  # No learning, this works for either random, or optimal
        r = []
        for i in range(1000):
            for t in range(self.H):
                a = p[self.curr_s, t]
                self.step(a, t)
            r.append(self.total_reward)
            self.reset()
        return r


# If we have the access to the true reward and transition, we should be able to do good
def optimal_policy(m):
    S = m.S
    H = m.H
    A = m.A
    policy = np.zeros((S, H), dtype=int)
    V = np.zeros((S, H + 1))
    V[:, H] = np.zeros(S)
    Q = np.zeros((S, A, H))
    for t in range(H - 1, -1, -1):
        for s in range(S):
            Q[s, :, t] = m.R[s, :, t] + np.dot(m.P[s, :, t, :], V[:, t + 1])
            policy[s, t] = np.argmax(Q[s, :, t])
            V[s, t] = max(Q[s, :, t])
    return policy


def get_avg(r):
    window = 1000
    average_r = []
    for ind in range(len(r) - window + 1):
        average_r.append(np.mean(r[ind:ind + window]))
    for ind in range(window - 1):
        average_r.insert(0, np.nan)
    return average_r


def cum_me(r):
    return np.cumsum(r) / range(1, len(r) + 1)


"""# Algorithms

## OTS
"""


# OTS
def OTS(m, epLen):
    S = m.S
    H = m.H
    A = m.A
    Q = np.zeros((S, A, H))
    V = np.zeros((S, H + 1))
    V[:, H] = np.zeros(S)
    delta = 1 / (S * A * (H ** 2) * (epLen ** 2))
    policy = np.random.choice(m.A, (m.S, m.H))
    for t in range(H - 1, -1, -1):
        policy, V, Q = OTS_step(t, S, H, A, Q, delta, m.emperical_rewards, m.empirical_transition, m.observations,
                                policy, V)
    return policy


@nb.njit()
def OTS_step(t, S, H, A, Q, delta, emperical_rewards, empirical_transition, observations, policy, V):
    for s in range(S):
        for a in range(A):
            # Compute param mu and sigma for the posterior distribution
            mu = emperical_rewards[s, a, t] / observations[s, a, t]
            P = empirical_transition[s, a, t, :]
            norm_P = np.linalg.norm(P)
            P /= norm_P if norm_P else 1

            sigma = min(H, np.sqrt((S * (H ** 3) * np.log(1 / delta)) / (observations[s, a, t])))

            # Sample reward, clip to empirical mean
            r = max(mu, np.random.normal(mu, sigma))

            # Compute Q
            Q[s, a, t] = r + np.dot(P, V[:, t + 1])

        # Update policy to the best arm in this round
        policy[s, t] = np.argmax(Q[s, :, t])
        V[s, t] = np.max(Q[s, :, t])
    return policy, V, Q


def run_OTS(m, epLen, p_init):
    r = []
    p = p_init
    for i in tqdm(range(epLen)):
        # Sampling
        for t in range(m.H):
            a = p[m.curr_s, t]
            m.step(a, t)
        r.append(m.total_reward)
        m.reset()
        # Update policy based on new stats
        p = OTS(m, epLen)
    return r


# OTS non-clip
def OTS_n(m, epLen):
    S = m.S
    H = m.H
    A = m.A
    Q = np.zeros((S, A, H))
    V = np.zeros((S, H + 1))
    V[:, H] = np.zeros(S)
    delta = 1 / (S * A * (H ** 2) * (epLen ** 2))
    policy = np.random.choice(m.A, (m.S, m.H))
    for t in range(H - 1, -1, -1):
        policy, V, Q = OTS_step_n(t, S, H, A, Q, delta, m.emperical_rewards, m.empirical_transition, m.observations,
                                  policy, V)
    return policy


@nb.njit()
def OTS_step_n(t, S, H, A, Q, delta, emperical_rewards, empirical_transition, observations, policy, V):
    for s in range(S):
        for a in range(A):
            # Compute param mu and sigma for the posterior distribution
            mu = emperical_rewards[s, a, t] / observations[s, a, t]
            P = empirical_transition[s, a, t, :]
            norm_P = np.linalg.norm(P)
            P /= norm_P if norm_P else 1

            sigma = min(H, np.sqrt((S * (H ** 3) * np.log(1 / delta)) / (observations[s, a, t])))

            # Sample reward, clip to empirical mean
            r = np.random.normal(mu, sigma)

            # Compute Q
            Q[s, a, t] = r + np.dot(P, V[:, t + 1])

        # Update policy to the best arm in this round
        policy[s, t] = np.argmax(Q[s, :, t])
        V[s, t] = np.max(Q[s, :, t])
    return policy, V, Q


def run_OTS_nonclip(m, epLen, p_init):
    r = []
    p = p_init
    for i in tqdm(range(epLen)):
        # Sampling
        for t in range(m.H):
            a = p[m.curr_s, t]
            m.step(a, t)
        r.append(m.total_reward)
        m.reset()
        # Update policy based on new stats
        p = OTS_n(m, epLen)
    return r


"""## OTS+"""


def OTS_plus(m, epLen):
    S = m.S
    H = m.H
    A = m.A
    Q = np.zeros((S, A, H))
    V = np.zeros((S, H + 1))
    V[:, H] = np.zeros(S)
    delta = 1 / (S * A * (H ** 2) * (epLen ** 2))
    policy = np.random.choice(m.A, (m.S, m.H))
    for t in range(H - 1, -1, -1):
        policy, V, Q = OTS_plus_step(t, S, H, A, Q, delta, m.emperical_rewards, m.empirical_transition, m.observations,
                                     policy, V)
    return policy


@nb.njit()
def OTS_plus_step(t, S, H, A, Q, delta, emperical_rewards, empirical_transition, observations, policy, V):
    for s in range(S):
        for a in range(A):
            # Compute param mu and sigma for the posterior distribution
            mu = emperical_rewards[s, a, t] / observations[s, a, t]
            P = empirical_transition[s, a, t, :]
            norm_P = np.linalg.norm(P)
            P /= norm_P if norm_P else 1
            sigma = min(H, np.sqrt((S * (H ** 3) * np.log(1 / delta)) / (observations[s, a, t])))

            # Sample reward, clip to empirical mean
            ucb = mu + 2 * sigma
            r = max(ucb, np.random.normal(mu, sigma))

            # Compute Q
            Q[s, a, t] = r + np.dot(P, V[:, t + 1])

        # Update policy to the best arm in this round
        policy[s, t] = np.argmax(Q[s, :, t])
        V[s, t] = max(Q[s, :, t])
    return policy, V, Q


def run_OTS_plus(m, epLen, p_init):
    r = []
    p = p_init
    for i in tqdm(range(epLen)):
        # Sampling
        for t in range(m.H):
            a = p[m.curr_s, t]
            m.step(a, t)
        r.append(m.total_reward)
        m.reset()
        # Update policy based on new stats
        p = OTS_plus(m, epLen)
    return r

"""## SSR"""


# Magnitude = [Hoeffiding, Bernstein]
def SSR(m, k, magnitude, epLen):
    S = m.S
    H = m.H
    A = m.A
    Q = np.zeros((S, A, H + 1))
    V = np.zeros((S, H + 1))
    zk = np.random.normal(0, 1)
    c = np.log(2 * H * S * A * k ** 2)

    for t in range(H - 1, -1, -1):
        Q, V = SSR_step(t, S, A, H, zk, c, magnitude, m.empirical_transition, m.emperical_rewards, m.observations, Q, V)
    return Q


@nb.njit
def SSR_step(t, S, A, H, zk, c, magnitude, empirical_transition, emperical_rewards, observations, Q, V):
    # Estimate Q on data with least square, then add noise
    for s in range(S):
        for a in range(A):
            nk = observations[s, a, t] + 1
            # Compute emperical reward etc
            sum = emperical_rewards[s, a, t] / nk
            P = empirical_transition[s, a, t, :] / nk
            Variance = 0
            diff = np.dot(P, V[:, t + 1])
            for s_next in range(S):
                sum += P[s_next] * V[s_next, t + 1]
                Variance += P[s_next] * (V[s_next, t + 1] - diff) ** 2
                # Compute simga (s,a,t)
            if magnitude == 0:
                sigma = H * np.sqrt(c / nk) + H / nk
            else:
                sigma = np.sqrt((16 * Variance * c) / nk) + (65 * H * c) / nk + np.sqrt(c / nk)
            sum += sigma * zk
            Q[s, a, t] = sum
            # Add clipping to V
            V[s, t] = max(-2 * (H - t + 1), min(a, max(Q[s_next, :, t])))
    return Q, V


def run_SSR(m, epLen, magnitude, p_init):
    r = []
    p = p_init
    for k in tqdm(range(epLen)):
        # Update Q_value based on new stats
        Q = SSR(m, k, magnitude, epLen)
        # Sampling via following Q greedily
        for t in range(m.H):
            if k == 0:
                a = p[m.curr_s, t]
            else:
                a = np.argmax(Q[m.curr_s, :, t])
            m.step(a, t)
        r.append(m.total_reward)
        m.reset()
    return r

"""## SSR"""
# UCBVI
def UCBVI(m, epLen):
    S = m.S
    H = m.H
    A = m.A
    Q = np.zeros((S, A, H))
    V = np.zeros((S, H + 1))
    V[:, H] = np.zeros(S)
    delta = 0.1
    scale = np.log(5 * S * A * epLen / delta)
    policy = np.random.choice(m.A, (m.S, m.H))
    for t in range(H - 1, -1, -1):
        policy, V, Q = UCBVI_step(t, S, H, A, Q, scale, m.emperical_rewards, m.empirical_transition, m.observations,
                                  policy, V)
    return policy


@nb.njit()
def UCBVI_step(t, S, H, A, Q, scale, emperical_rewards, empirical_transition, observations, policy, V):
    for s in range(S):
        for a in range(A):
            # Compute empirical mean and transition kernel
            mu = emperical_rewards[s, a, t] / observations[s, a, t]
            P = empirical_transition[s, a, t, :]
            norm_P = np.linalg.norm(P)
            P /= norm_P if norm_P else 1

            # Compute bonus
            n_sat = observations[s, a, t]
            r_bonus = 7 * H * np.sqrt(1 / n_sat) * scale

            # Compute Q
            V_next = np.dot(P, V[:, t + 1])
            Q[s, a, t] = mu + r_bonus + V_next

        # Update policy to the best arm in this round
        policy[s, t] = np.argmax(Q[s, :, t])
        V[s, t] = np.max(Q[s, :, t])
    return policy, V, Q


def run_UCBVI(m, epLen, p_init):
    r = []
    p = p_init
    for i in tqdm(range(epLen)):
        # Sampling
        for t in range(m.H):
            a = p[m.curr_s, t]
            m.step(a, t)
        r.append(m.total_reward)
        m.reset()
        # Update policy based on new stats
        p = UCBVI(m, epLen)
    return r

def dispatch(args):
    algo_id, params = args
    m, epLen, p_rand = params
    if algo_id == 0:
        r_ots = run_OTS(m, epLen, p_rand)
        return r_ots
    elif algo_id == 1:
        r_ots_plus = run_OTS_plus(m, epLen, p_rand)
        return r_ots_plus
    elif algo_id == 2:
        r_ots_nonclip = run_OTS_nonclip(m, epLen, p_rand)
        return r_ots_nonclip
    elif algo_id == 3:
        magnitude = 1 #this is bad code, but this is the only algo that takes a different parameters. Sorry sigh.
        r_ssr = run_SSR(m, epLen, magnitude, p_rand)
        return r_ssr
    elif algo_id == 4:
        r_ucbvi = run_UCBVI(m, epLen, p_rand)
        return r_ucbvi

"""# Experiment"""
def main(args):

    S = args.S
    A = args.A
    H = args.H
    epLen = args.epLen
    workdir = args.workdir

    os.chdir(workdir)
    
    with open("config.txt", "w") as f:
        json.dump(args.__dict__, f, indent=2)

    m = MDP(S, A, H)
    p_rand = np.random.choice(m.A, (m.S, m.H))
    ms = [copy.deepcopy(m) for _ in range(N_ALGORITHMS)]
    ps = [copy.deepcopy(p_rand) for _ in range(N_ALGORITHMS)]
    
    with Pool(processes = N_ALGORITHMS) as pool:
        results = pool.map(dispatch, [(algo_id, (ms[algo_id], epLen, ps[algo_id])) for algo_id in range(N_ALGORITHMS)])
    
    r_ots, r_ots_plus, r_ots_nonclip, r_ssr, r_ucbvi = results

    
    np.savetxt('ssr_s{}.txt'.format(S), r_ssr, fmt="%.3f")
    np.savetxt('ots_s{}.txt'.format(S), r_ots, fmt="%.3f")
    np.savetxt('ucbvi_s{}.txt'.format(S), r_ucbvi, fmt="%.3f")
    np.savetxt('ots_plus_s{}.txt'.format(S), r_ots_plus, fmt="%.3f")
    np.savetxt('ots_nonclip_s{}.txt'.format(S), r_ots_nonclip, fmt="%.3f")

    ssr = np.loadtxt('ssr_s{}.txt'.format(S), unpack=True)
    ots = np.loadtxt('ots_s{}.txt'.format(S), unpack=True)
    ucbvi = np.loadtxt('ucbvi_s{}.txt'.format(S), unpack=True)
    ots_plus = np.loadtxt('ots_plus_s{}.txt'.format(S), unpack=True)
    ots_n = np.loadtxt('ots_nonclip_s{}.txt'.format(S), unpack=True)

    plt.plot(cum_me(ots),label="OTS")
    plt.plot(cum_me(ots_plus),label="OTS+")
    plt.plot(cum_me(ots_n),label="OTS_nonclip")
    plt.plot(cum_me(ssr), label="SSR")
    plt.plot(cum_me(ucbvi), label="UCB_VI")
    plt.title("S = {}, A = {}, H = {}".format(S, A, H))
    plt.xlabel("Episode")
    plt.ylabel("Reward")
    plt.legend()
    plt.savefig("trace.png", dpi=500)
    plt.show()

if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("-S", default = 5, type=int)
    parser.add_argument("-A", default = 3, type=int)
    parser.add_argument("-H", default = 10, type=int)
    parser.add_argument("--epLen", default = 10000, type=int)
    parser.add_argument("--workdir", required=True)
    args = parser.parse_args()
    main(args)
