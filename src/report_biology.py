"""Render stored biology snapshots only; never perform API or model calculations."""
def add_string_section(doc, biology, add_table, picture=None):
    doc.add_heading('Target STRING context', level=2)
    data = (biology or {}).get('string') or {}
    doc.add_paragraph('STRING functional associations provide biological context; '
                      'they do not demonstrate ligand binding or activity.')
    if data.get('error'):
        doc.add_paragraph('STRING unavailable: ' + str(data['error']))
    if data.get('unmapped'):
        doc.add_paragraph('Targets without verified protein and species mapping: '
                          + ', '.join(data['unmapped']))
    groups = data.get('groups') or []
    if not groups:
        doc.add_paragraph('No target STRING snapshot was recorded for this run.')
    for group in groups:
        doc.add_heading(f"STRING species {group['species']}", level=3)
        add_table(doc, [(target, accession) for target, accession in group.get('mapping', {}).items()])
        doc.add_paragraph('Query date: ' + str(group.get('created_at', 'Not recorded')))
        doc.add_paragraph('Enrichment scope: ' + str(group.get('enrichment_scope', 'Not recorded')))
        if group.get('unmapped'):
            doc.add_paragraph('Not mapped by STRING: ' + ', '.join(group['unmapped']))
        if group.get('error'):
            doc.add_paragraph('Network unavailable: ' + str(group['error']))
        result = group.get('result') or {}
        if result.get('network_svg') and picture:
            picture(result['network_svg'], f"STRING functional association network for species {group['species']}")
        partners = result.get('partners') or []
        if partners:
            table = doc.add_table(rows=1, cols=3, style='Table Grid')
            for cell, text in zip(table.rows[0].cells, ['Protein A', 'Protein B', 'Confidence score']):
                cell.text = text
            for partner in partners:
                cells = table.add_row().cells
                for cell, value in zip(cells, [partner.get('preferredName_A'),
                       partner.get('preferredName_B'), partner.get('score')]):
                    cell.text = str(value if value is not None else 'Unavailable')
        terms = result.get('enrichment') or []
        if terms:
            table = doc.add_table(rows=1, cols=3, style='Table Grid')
            for cell, text in zip(table.rows[0].cells, ['Category', 'Functional term', 'FDR']):
                cell.text = text
            for term in terms:
                for cell, value in zip(table.add_row().cells,
                        [term.get('category'), term.get('description'), term.get('fdr')]):
                    cell.text = str(value if value is not None else 'Unavailable')


def add_adme_section(doc, biology, add_table):
    doc.add_heading('Top docking candidate ADME', level=2)
    data = (biology or {}).get('adme') or {}
    doc.add_paragraph('Candidates are selected within each target using the lowest finite '
        'docking score among completed interaction-profiled pairs. Ties are retained. '
        'These are computational candidates, not experimentally established leads.')
    if data.get('error'):
        doc.add_paragraph('ADME unavailable: ' + str(data['error']))
    if data.get('no_candidate'):
        doc.add_paragraph('No eligible candidate for ADME: ' + ', '.join(str(t) for t in data['no_candidate']))
    if not data.get('compounds'):
        doc.add_paragraph('No top-candidate ADME calculation was recorded for this run.')
    for entry in data.get('compounds') or []:
        doc.add_heading(', '.join(entry.get('labels') or ['Compound']), level=3)
        doc.add_paragraph('Targets: ' + ', '.join(entry.get('targets') or []))
        doc.add_paragraph('Input structure SMILES: ' + str(entry.get('smiles', 'Not recorded')))
        for name, title in [('descriptors', 'Calculated descriptors and heuristic rules'),
                            ('ml', 'ADMET AI predictions')]:
            doc.add_heading(title, level=4)
            output = entry.get(name) or {}
            if output.get('_error'):
                doc.add_paragraph(str(output['_error']))
            endpoints = output.get('_verification', {}).get('endpoints') or {}
            if endpoints:
                add_table(doc, [(label, f"{endpoint.get('value') if endpoint.get('value') is not None else 'Unavailable'} "
                        f"{endpoint.get('unit', '')} [{endpoint.get('status', 'unavailable')}]")
                        for label, endpoint in endpoints.items()])
            else:
                values = [(label, value) for label, value in output.items()
                          if not label.startswith('_') and label != 'status']
                if values:
                    add_table(doc, values)
            verification = output.get('_verification') or {}
            if verification:
                doc.add_paragraph('Method: ' + str(verification.get('method', 'Not recorded'))
                    + '. Version: ' + str(verification.get('model_version') or
                                          verification.get('rdkit_version') or 'Not recorded'))
    for error in data.get('errors') or []:
        doc.add_paragraph(f"ADME unavailable for {error.get('ligand')} ({error.get('target')}): {error.get('error')}")


def render_biology_panel(st, biology):
    """Website view of the same immutable snapshots consumed by the report."""
    with st.expander('Target STRING context', expanded=False):
        data = biology.get('string') or {}
        if data.get('error'):
            st.info('STRING unavailable: ' + str(data['error']))
        if data.get('unmapped'):
            st.caption('No verified mapping: ' + ', '.join(data['unmapped']))
        for group in data.get('groups') or []:
            st.caption(f"Species {group['species']} · {group.get('created_at', 'date unavailable')}")
            result = group.get('result') or {}
            if result.get('network_svg'):
                # Use the standard image path instead of embedding external markup.
                import base64
                st.image('data:image/svg+xml;base64,' + base64.b64encode(
                    result['network_svg'].encode('utf-8')).decode('ascii'))
            if group.get('error'):
                st.info(str(group['error']))
            if result.get('partners'):
                st.dataframe(result['partners'], use_container_width=True)
            if result.get('enrichment'):
                st.dataframe(result['enrichment'], use_container_width=True)
            if group.get('unmapped'):
                st.caption('Not mapped by STRING: ' + ', '.join(group['unmapped']))
    with st.expander('Top docking candidate ADME', expanded=False):
        data = biology.get('adme') or {}
        if data.get('error'):
            st.info(str(data['error']))
        for entry in data.get('compounds') or []:
            st.markdown('**' + ', '.join(entry['labels']) + '**')
            st.caption('Targets: ' + ', '.join(entry['targets']))
            for name in ('descriptors', 'ml'):
                output = entry.get(name) or {}
                if output.get('_error'):
                    st.info(str(output['_error']))
                endpoints = output.get('_verification', {}).get('endpoints') or {}
                if endpoints:
                    st.dataframe([dict(Endpoint=label, **endpoint)
                                  for label, endpoint in endpoints.items()], use_container_width=True)
