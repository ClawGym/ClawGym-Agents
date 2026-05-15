\section{Methodology}\label{sec:method}

In this section, we present the methodology in a manner that is intended to be comprehensive while still being accessible. In order to set the stage, we first formalize the problem and then move through the objective, optimization routine, and implementation details. It is worth noting that the core training loop follows standard empirical risk minimization~\cite{vapnik1992,shalev2014}, and we leverage widely adopted stochastic optimization techniques~\cite{kingma2015adam}.

\paragraph{Problem setup.}
Let $\mathcal{D}=\{(x_i,y_i)\}_{i=1}^n$ denote the dataset with $n$ independent examples, where $x_i \in \mathcal{X}$ and $y_i \in \mathcal{Y}$. We consider a parametric model $f_\theta:\mathcal{X}\to\mathcal{Y}$ with parameters $\theta \in \Theta$. The loss for an example $(x_i,y_i)$ is given by $\ell(f_\theta(x_i),y_i)$. The aggregate training loss is
$L(\theta)=\sum_{i=1}^n \ell(f_\theta(x_i), y_i)$,
which we will minimize with a regularization term to avoid overfitting, consistent with the aforementioned literature~\cite{vapnik1992,shalev2014}.

\paragraph{Objective.}
Our learning objective is an $\ell_2$-regularized empirical risk, written as:

\begin{equation}
\min_{\theta\in\Theta} \ \frac{1}{n}\sum_{i=1}^n \ell(f_\theta(x_i), y_i) + \lambda \,\Omega(\theta),
\label{eq:objective}
\end{equation}

where $\Omega(\theta)=\tfrac{1}{2}\|\theta\|_2^2$ and $\lambda\ge 0$ controls regularization strength. In order to make the notation consistent with common practice, we retain the factor $1/n$ outside the summation. The convexity of $\Omega$ and smoothness assumptions on $\ell$ are standard~\cite{shalev2014}. See Eq.~\ref{eq:objective} for the exact structure used in all experiments.

\paragraph{Stochastic optimization.}
We utilize a minibatch-based stochastic optimizer. Specifically, at iteration $t$, we draw a minibatch $\mathcal{B}_t \subset \{1,\dots,n\}$ of size $b$ and estimate the gradient $\nabla_\theta \widehat{L}(\theta^t; \mathcal{B}_t)$. It is worth noting that, under uniform sampling without replacement, this estimator is unbiased for the population gradient. We then apply an Adam-style update~\cite{kingma2015adam}, which we describe abstractly below to maintain generality.

\begin{equation}
\theta^{t+1} = \theta^{t} - \eta_t \, \nabla_\theta \widehat{L}(\theta^t; \mathcal{B}_t).
\label{eq:update}
\end{equation}

Although we leverage adaptive moment estimates in practice, Eq.~\ref{eq:update} captures the essential descent step used by our training loop. In order to stabilize early training, we employ a linear warm-up for $\eta_t$ over the first $T_\text{warm}$ steps and then decay it according to a cosine schedule, as commonly recommended~\cite{kingma2015adam}.

\paragraph{Algorithmic procedure.}
Algorithm~\ref{alg:train} (referenced from Section~\ref{sec:method}) summarizes our training loop: initialize $\theta^0$, set optimizer state, and iterate for $T$ steps. Each step samples $\mathcal{B}_t$, computes the gradient with respect to the current parameters, applies the update in Eq.~\ref{eq:update}, and, if applicable, applies weight decay consistent with the objective in Eq.~\ref{eq:objective}. It is worth noting that we also apply gradient clipping by global norm at a threshold $c$, which is a widely used stabilization technique in modern training regimes~\cite{kingma2015adam}.

\paragraph{Complexity and memory.}
The per-iteration time complexity is $O(b \cdot C_f)$, where $C_f$ denotes the cost of a forward/backward pass of $f_\theta$. Memory usage is dominated by activations and optimizer state; Adam maintains first and second moments, thereby approximately tripling parameter storage. In order to make training feasible under constrained memory budgets, we utilize mixed-precision arithmetic (FP16) with loss scaling, which preserves numerical stability in practice while reducing memory footprint. It is worth noting that our code path falls back to full precision if underflow is detected.

\paragraph{Implementation details.}
We implement the training loop in a standard deep learning framework with automatic differentiation. Batch size $b$, total steps $T$, warm-up steps $T_\text{warm}$, and base learning rate $\eta_0$ are tuned on a held-out validation set using a simple grid search; the final choices are reported alongside results. We also leverage deterministic dataloading where possible to facilitate reproducibility. All experiments use the same random seed per dataset to avoid confounds. For completeness, we provide the following summary of the loss used during training:
$L(\theta)=\sum_{i=1}^n \ell(f_\theta(x_i), y_i)$,
which is the unnormalized form; the normalized counterpart appears in Eq.~\ref{eq:objective}. It is worth noting that this distinction is purely notational and does not affect the gradients under a fixed $n$.

\paragraph{Assumptions and limitations.}
Our analysis presumes that $\ell$ is Lipschitz-smooth and that minibatches are sampled uniformly at random. While these are standard in the literature~\cite{shalev2014}, deviations (e.g., curriculum sampling) may modify convergence behavior. In order to keep the exposition streamlined, we do not further elaborate on such variants here; however, the algorithmic skeleton in Algorithm~\ref{alg:train} remains applicable.

Finally, for cross-reference, we remind the reader that Section~\ref{sec:method} provides the formal statement of the problem and Eq.~\ref{eq:objective} encodes the training criterion that is consistently used across all datasets. The reader may refer back to these items when interpreting ablations and sensitivity analyses in the subsequent sections.