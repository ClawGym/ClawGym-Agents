Subject: Midweek Update: Preliminary Comparisons and a Few Caveats

Hi team,

I wanted to share a long-ish prelude to our next sync because I ran the latest experiments and there are some things to unpack. First off, we tried the graph smoothness idea again (you’ll see me call it the Laplacian thing in the doc) and also another pass of the convex relaxation that we’ve been talking about; I know there are different shorthands floating around for these and I’ll clean it up later.

The basic story is positive but I don’t want to get ahead of the data. Runtime and the metric choice both factor in. There’s one run where the metric is MAE (not RMSE), and one where a value didn’t get written, so the interpretation takes a bit of care. I’ll put more detailed numbers in the report, but the general pattern seems consistent with what we expected: the convex approach takes longer, sometimes outperforms.

I’ll stop here before this gets too long—happy to summarize in a cleaner way once we have the final numbers and a clear subject line.

Thanks!
