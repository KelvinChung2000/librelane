from concurrent.futures import ThreadPoolExecutor

from loguru import logger


def test_submitted_callables_inherit_logging_context():
    """
    A step binding established in the submitting thread must survive into the
    worker thread.

    ``contextvars`` give every new thread a fresh, empty context, so a plain
    ``ThreadPoolExecutor.submit`` silently drops whatever
    ``logger.contextualize`` established in the caller. Steps that fan out
    internally -- ``OpenROAD.STAPrePNR`` submits one job per timing corner --
    would emit records with no step attribution at all.
    """
    from librelane.common.tpe import ContextPropagatingThreadPoolExecutor

    seen: list[str | None] = []
    sink_id = logger.add(
        lambda message: seen.append(message.record["extra"].get("step")),
        format="{message}",
        level=0,
    )
    try:
        with ContextPropagatingThreadPoolExecutor(max_workers=2) as tpe:
            with logger.contextualize(step="Yosys.Synthesis"):
                tpe.submit(logger.info, "from worker").result()
    finally:
        logger.remove(sink_id)

    assert seen == ["Yosys.Synthesis"]


def test_plain_executor_loses_logging_context():
    """
    Pins the behaviour that motivates the subclass, so the propagation test
    above cannot pass vacuously.
    """
    seen: list[str | None] = []
    sink_id = logger.add(
        lambda message: seen.append(message.record["extra"].get("step")),
        format="{message}",
        level=0,
    )
    try:
        with ThreadPoolExecutor(max_workers=2) as tpe:
            with logger.contextualize(step="Yosys.Synthesis"):
                tpe.submit(logger.info, "from worker").result()
    finally:
        logger.remove(sink_id)

    assert seen == [None]


def test_context_propagates_through_nested_executors():
    """
    Nested fan-out must keep attribution: the flow submits a step, and the step
    submits per-corner work of its own.
    """
    from librelane.common.tpe import ContextPropagatingThreadPoolExecutor

    seen: list[str | None] = []
    sink_id = logger.add(
        lambda message: seen.append(message.record["extra"].get("step")),
        format="{message}",
        level=0,
    )

    inner = ContextPropagatingThreadPoolExecutor(max_workers=2)

    def step_body():
        with logger.contextualize(step="OpenROAD.STAPrePNR"):
            inner.submit(logger.info, "corner nom_tt").result()

    try:
        with ContextPropagatingThreadPoolExecutor(max_workers=2) as outer:
            outer.submit(step_body).result()
    finally:
        inner.shutdown()
        logger.remove(sink_id)

    assert seen == ["OpenROAD.STAPrePNR"]
