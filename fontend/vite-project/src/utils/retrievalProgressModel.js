export const STAGE_ORDER = ['router', 'retrieval', 'grader', 'rewrite', 'generation'];

const LEGACY_STAGE_MAP = {
  graph: 'retrieval',
  graphProgress: 'retrieval',
  vector: 'retrieval',
  vectorProgress: 'retrieval',
  fulltext: 'retrieval',
  fulltextProgress: 'retrieval',
  aiProgress: 'generation',
};

export const createInitialStages = (t) => ({
  router: { key: 'router', name: t('retrieval.router'), status: 'waiting', count: null, hits: null },
  retrieval: { key: 'retrieval', name: t('retrieval.retrieval'), status: 'waiting', count: null, hits: null },
  grader: { key: 'grader', name: t('retrieval.grader'), status: 'waiting', count: null, hits: null },
  rewrite: { key: 'rewrite', name: t('retrieval.rewrite'), status: 'waiting', count: 0, hits: null },
  generation: { key: 'generation', name: t('retrieval.generation'), status: 'waiting', count: null, hits: null },
});

export const normalizeProgressType = (type) => LEGACY_STAGE_MAP[type] || type;

const markCompleted = (stage) => {
  if (stage && stage.status !== 'waiting') {
    stage.status = 'completed';
  }
};

const updateStageMetrics = (stage, event) => {
  if (stage.key === 'rewrite') {
    stage.count = Math.max(stage.count || 0, Number.isFinite(event?.data) ? event.data : 1);
    return;
  }

  if (typeof event?.data === 'number') {
    stage.hits = event.data;
  }
};

export const buildRetrievalProgressModel = (messages = [], t) => {
  const stages = createInitialStages(t);
  let activeStageKey = null;

  messages.forEach((event) => {
    const stageKey = normalizeProgressType(event?.type);

    if (event?.type === 'result') {
      markCompleted(stages[activeStageKey]);
      stages.generation.status = 'completed';
      activeStageKey = null;
      return;
    }

    if (!STAGE_ORDER.includes(stageKey)) {
      return;
    }

    if (activeStageKey && activeStageKey !== stageKey) {
      markCompleted(stages[activeStageKey]);
    }

    const stage = stages[stageKey];
    updateStageMetrics(stage, event);

    if (stage.status === 'waiting') {
      stage.status = 'running';
    } else if (stage.status === 'completed') {
      stage.status = 'running';
    }

    if (event?.message && /completed/i.test(event.message)) {
      stage.status = 'completed';
      activeStageKey = null;
      return;
    }

    activeStageKey = stageKey;
  });

  const stageList = STAGE_ORDER.map((key) => stages[key]);
  const isCompleted = stageList.every((stage) => stage.status === 'completed')
    || stages.generation.status === 'completed';
  const completedCount = stageList.filter((stage) => stage.status === 'completed').length;
  const runningCount = stageList.filter((stage) => stage.status === 'running').length;
  const percent = isCompleted
    ? 100
    : Math.round(((completedCount + runningCount * 0.5) / stageList.length) * 100);
  const latestMessage = [...messages]
    .reverse()
    .find((event) => event?.type !== 'result' && event?.message)?.message;

  return {
    stages: stageList,
    isCompleted,
    percent,
    latestMessage,
  };
};
