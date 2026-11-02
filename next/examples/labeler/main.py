from polaris_platform.sdk import Component


def create():
    component = Component()
    labels = {}

    @component.operation('label', access='write', requires={'note': 'notes.read@1'})
    def label_note(note_id, ctx):
        note = ctx.call_required('note', {'id': note_id})
        words = (note['title'] + ' ' + note['body']).lower().split()
        tags = sorted(set(word.strip('.,!?') for word in words if len(word) >= 4))[:3]
        labels[note_id] = tags
        return {'note_id': note_id, 'tags': tags}

    @component.operation('get')
    def get_labels(note_id):
        return {'note_id': note_id, 'tags': list(labels.get(note_id, []))}

    return component


if __name__ == '__main__':
    create().run()
