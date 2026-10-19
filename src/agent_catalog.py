"""User-facing workflow names; does not change engines or service routing."""

AGENTS = (
    {'name': 'Pose', 'role': 'Docking and ligand–residue interactions', 'actions': ('dock', 'docking', 'structure')},
    {'name': 'Fate', 'role': 'ADME, toxicity and drug-likeness', 'actions': ('analyze', 'admet', 'druglikeness')},
    {'name': 'Nexus', 'role': 'STRING and network pharmacology', 'actions': ('string',)},
    {'name': 'Quill', 'role': 'Scientific reports and structure exports', 'actions': ('report', 'export')},
    {'name': 'Orbit', 'role': 'Calculated HOMO/LUMO energies and surfaces', 'actions': ('qm',)},
    {'name': 'Atlas', 'role': 'Target preparation and Ramachandran validation', 'actions': ('ramachandran', 'validation')},
    {'name': 'Compass', 'role': 'Disease-related target discovery', 'actions': ('target', 'target_finder')},
    {'name': 'Flux', 'role': 'Biotransformation and metabolism prediction', 'actions': ('metabolism',)},
    {'name': 'Helix', 'role': 'BLAST, sequence relationships and phylogeny', 'actions': ('blast', 'alignment', 'phylogeny')},
    {'name': 'Anchor', 'role': 'Molecular dynamics and pose stability', 'actions': ('md',)},
    {'name': 'Scout', 'role': 'Ligand discovery and screening', 'actions': ('scout',)},
)


def agent_for(action):
    action = str(action or '').strip().lower()
    return next((agent['name'] for agent in AGENTS if action in agent['actions']), None)

