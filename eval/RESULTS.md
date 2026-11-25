# Eval results per question

Generated from `eval_report.json` (run `make eval` to regenerate).

## test: 75.0% accuracy, 36 questions

| id | type | result | refused | question |
|---|---|---|---|---|
| T-01 | version_conflict | correct | no | How many minor versions may the kubelet lag behind kube-apiserver? |
| T-02 | version_conflict | correct | no | What is the maturity of swap memory support on Linux nodes? |
| T-03 | version_conflict | correct | no | Is Pod scheduling readiness (schedulingGates) alpha, beta or stable? |
| T-04 | version_conflict | correct | no | What is the feature state of user namespaces for Pods? |
| T-05 | version_conflict | correct | no | Are gRPC liveness probes stable? |
| T-06 | version_conflict | **wrong** | no | Can I use .spec.ordinals to set a StatefulSet's start ordinal, and is it stable? |
| T-07 | version_conflict | **wrong** | no | Should I still use KMS v1 for encryption at rest? |
| T-08 | version_conflict | correct | no | What is the feature state of Evented PLEG? |
| T-09 | version_conflict | correct | no | Is the Job pod failure policy feature generally available? |
| T-10 | unanswerable | correct | yes | What is the maximum number of nodes a single Kubernetes cluster officially supports? |
| T-11 | unanswerable | correct | yes | How much RAM should I give etcd for a 500-node cluster? |
| T-12 | unanswerable | correct | yes | On what date was Kubernetes v1.31 released? |
| T-13 | unanswerable | correct | yes | What uptime SLA does the Kubernetes API server guarantee? |
| T-14 | unanswerable | correct | yes | What are the default CPU and memory requests for the CoreDNS deployment? |
| T-15 | unanswerable | correct | yes | What is the recommended maximum number of Services per namespace? |
| T-16 | unanswerable | correct | yes | How long does a kubeadm upgrade from 1.30 to 1.31 usually take? |
| T-17 | unanswerable | correct | yes | Which cloud providers are certified conformant for Kubernetes 1.31? |
| T-18 | false_premise | correct | yes | How do I set the kubelet --max-pod-lag flag to allow more version skew? |
| T-19 | false_premise | correct | yes | What does the PodAutoRepair feature gate do, and when did it graduate to stable? |
| T-20 | false_premise | correct | yes | How do I enable automatic swap tuning with the kubelet --enable-swap-autotune flag? |
| T-21 | version_gap | correct | no | How do I mount an OCI image as a volume in a Pod? |
| T-22 | version_gap | correct | no | What is a VolumeAttributesClass used for? |
| T-23 | version_gap | **wrong** | yes | How do sidecar containers work when declared as init containers with restartPolicy Always? |
| T-24 | version_gap | correct | no | What is the default node-monitor-grace-period? |
| T-25 | factual | correct | no | What is the default terminationGracePeriodSeconds for a Pod? |
| T-26 | factual | **wrong** | yes | What is the default port range for NodePort Services? |
| T-27 | factual | correct | no | How much data can a ConfigMap hold? |
| T-28 | factual | **wrong** | yes | What is the size limit of an individual Secret? |
| T-29 | factual | correct | no | How long can a label value be? |
| T-30 | factual | **wrong** | yes | Where are node heartbeat Lease objects stored? |
| T-31 | factual | correct | no | How does the pod-deletion-cost annotation affect ReplicaSet scale-down? |
| T-32 | factual | correct | no | How can finished Jobs be cleaned up automatically? |
| T-33 | procedural | **wrong** | yes | How do I safely drain a node before maintenance? |
| T-34 | procedural | correct | no | How do I create a Secret with kubectl? |
| T-35 | procedural | **wrong** | yes | How do I enable encryption at rest for Secret data? |
| T-36 | procedural | **wrong** | no | How do I make a Pod run on a specific node using labels? |

## dev: 60.0% accuracy, 10 questions

| id | type | result | refused | question |
|---|---|---|---|---|
| D-01 | version_conflict | correct | no | What is the feature state of the node log query feature? |
| D-02 | version_conflict | correct | no | Is API Priority and Fairness stable? |
| D-03 | unanswerable | correct | yes | What is the default value of the kubelet --max-pods flag? |
| D-04 | unanswerable | correct | yes | How much does running a cluster on EKS cost per month? |
| D-05 | false_premise | correct | yes | What does the --eviction-grace-multiplier kubelet flag control? |
| D-06 | version_gap | **wrong** | yes | What does coordinated leader election do? |
| D-07 | factual | correct | no | What is the default restartPolicy for a Pod? |
| D-08 | factual | **wrong** | yes | What namespaces does Kubernetes start with? |
| D-09 | factual | **wrong** | yes | How long can the name segment of an annotation key be? |
| D-10 | procedural | **wrong** | no | How do I expose ConfigMap data to a Pod as environment variables? |

## postfail: 80.0% accuracy, 10 questions

| id | type | result | refused | question |
|---|---|---|---|---|
| P-01 | version_conflict | correct | no | What is the feature state of contextual logging? |
| P-02 | version_conflict | correct | no | Can I scale an Indexed Job by changing parallelism and completions, and is that stable? |
| P-03 | version_conflict | correct | no | Is HPA support for container resource metrics stable? |
| P-04 | version_conflict | **wrong** | yes | What is the feature state of the ReadWriteOncePod access mode? |
| P-05 | version_conflict | **wrong** | yes | What is the maturity of the PodReadyToStartContainers (pod network readiness) condition? |
| P-06 | version_conflict | correct | no | Are Pod disruption conditions such as DisruptionTarget a stable feature? |
| P-07 | unanswerable | correct | yes | What is the maximum number of Pods allowed in one namespace? |
| P-08 | unanswerable | correct | yes | How many control plane nodes are recommended for a 2,000-node cluster? |
| P-09 | false_premise | correct | yes | What does the kubelet --swap-burst-limit flag control? |
| P-10 | version_gap | correct | no | How do I add more Service IP ranges using a ServiceCIDR object? |
