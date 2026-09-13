# Working on ml-platform

This platform is both a working product and a way to learn how its parts work. The owner is experienced in Python and machine learning and wants to understand the code, service boundaries, persistence, failure behavior, and infrastructure decisions. Build incrementally through readable worksheets, with AI assistance at the module level. A working system is the outcome of those understood steps.

All instructions needed for this approach live in this repository. [docs/worksheets/README.md](docs/worksheets/README.md) defines the sequence and working method; each milestone worksheet specifies its own implementation and tests.

Use three units of work: a milestone delivers an observable platform capability; a module develops one mechanism or service boundary within it; a checkpoint demonstrates that module through passing behavioral tests and an explanation of the result. A worksheet covers one milestone and names the modules in dependency order. Application code accumulates across milestones.

When writing a worksheet:

If the user requests an orientation sketch, give the outcome, proposed modules, test expectations, and open decisions, and label it as a sketch. Defer exact interfaces and runnable setup until the preceding implementation provides enough evidence. The full worksheet requirements below apply when expanding it for implementation.

1. Start with what the learner will build and one concrete request, input, or experiment they can follow through the system. State the first action clearly.
2. List prerequisites, tools, required services/accounts, and resource or cost requirements. Define unfamiliar terms when the example first needs them.
3. Specify observable behavior, inputs and outputs, ownership of data, state changes, errors, and the limits of this milestone. Distinguish implemented behavior from later architecture targets.
4. Propose the files and incomplete interfaces: signatures, docstrings, and TODOs. Supply enough detail to begin without providing the finished implementation of the mechanism being learned.
5. Break implementation into bounded modules. Each module states what to change, what to inspect, the test command, and the expected assertions, including relevant failure or boundary cases.
6. Include a final integrated exercise and a place to record actual commands, results, explanations, and limitations. A reader should be able to reproduce the work using only this repository and linked public technical documentation.

Use Markdown worksheets and ordinary source files, terminal commands, and tests. Notebooks are optional scratch space. Keep prose concrete: explain why a database transaction is needed using the job submission example before introducing distributed-systems terminology.

- A request to write or revise a worksheet authorizes documentation work. Leave application implementation to the learner unless they request it.
- For implementation help, work on the module or checkpoint the user selected. Explain its mechanism, assist with bounded code changes, and run its relevant tests. Do not interpret starting a worksheet as permission to implement the entire milestone or production system.
- Complete the requested module without repeatedly asking permission for routine edits or tests. Report the result and the next checkpoint; continue into another module when the user requests it or has explicitly included it in scope.
- Read the relevant worksheet and existing code before changing interfaces. Keep the worksheet aligned with decisions accepted during implementation.
- Introduce unfamiliar infrastructure concepts through a concrete example. The user knows Python and ML; Azure infrastructure and DevOps are learning topics.
- Worksheet interfaces may contain signatures and TODOs. Explain expected inputs, outputs, failure behavior, and tests without supplying the finished mechanism as an unsolicited solution.
- Tests should check externally meaningful behavior, boundary cases, and failures. Do not mark a checkpoint complete with required tests skipped, xfailed, or assertions weakened to match a bug.
- Distinguish planned commands/tests from commands actually run. Record limitations honestly; passing local tests is not evidence of Azure compatibility or production readiness.
- Preserve the minimal dashboard in milestone 1. Keep the approved architecture and milestone sequence in [docs/specs/README.md](docs/specs/README.md).
