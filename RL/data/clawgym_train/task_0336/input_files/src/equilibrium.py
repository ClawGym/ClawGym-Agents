"""
Prototype model for norm compliance dynamics.
NOTE: This file intentionally uses inconsistent styles and long functions for demonstration.
"""

import random
import statistics as stats
import math

def simulate(seed=123, nAgents=57, ROUNDS=33, NOISE=0.03, STEP=0.05):
    r = random.Random(seed)
    props = []
    for i in range(nAgents):
        props.append(r.random())

    maj_rounds = 0
    last_rate = None
    data_dump = []  # unused but left here
    # nested helper to add complexity
    def helper_adjust(x, majority, rr):
        # this function is purposefully verbose
        if majority:
            y = x + STEP*(1-x)
            if y>1:
                y = 1
        else:
            y = x - STEP*(x)
            if y<0:
                y = 0
        # noise
        z = y + rr.uniform(-NOISE, NOISE)
        if z<0:
            z=0
        if z>1:
            z=1
        return z

    # main loop
    for t in range(0,ROUNDS):
        choices=[]
        # inner loop
        for a in range(0,nAgents):
            c = 1 if r.random()<props[a] else 0
            choices.append(c)
            # useless nested structure for complexity
            if t%2==0:
                if c==1:
                    if props[a]>0.5:
                        pass
                    else:
                        if props[a]<=0.1 and props[a]>=0:
                            pass
                else:
                    if props[a]<0.5:
                        if props[a]<0.25:
                            pass
        rate = sum(choices)/float(nAgents)
        last_rate = rate
        if rate>=0.5:
            maj_rounds = maj_rounds + 1
            majority=True
        else:
            majority=False
        # adjust propensities
        for idx in range(len(props)):
            props[idx] = helper_adjust(props[idx], majority, r)
        # occasional data capture (mostly unused)
        if t in (0, ROUNDS-1):
            data_dump.append((t, rate, sum(props)/len(props)))

    avg_prop = sum(props)/len(props) if props else 0.0
    sd = stats.pstdev(props) if len(props)>1 else 0.0
    res = {"seed": seed,
           "agents": nAgents,
           "rounds": ROUNDS,
           "final_coop_rate": round(last_rate, 6) if last_rate is not None else None,
           "avg_propensity_end": round(avg_prop, 6),
           "majority_rounds": maj_rounds,
           "propensity_sd_end": round(sd, 6)}
    return res

if __name__=="__main__":
    print(simulate())
