export const state = {
  overview: null,
  current: null,
  opsData: null,
  memoryData: null,
  skillData: null,
  preferenceData: null,
  view: 'classic',
  memoryTab: 'knowledge',
  opsGame: '',
  opsDays: '7',
  listFilter: '',
  modalDispose: null,
};

export const parts = () => location.hash.slice(1).split('/').filter(Boolean);
