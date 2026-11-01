from polaris_platform.sdk import Component


def create():
    component = Component()
    notes = {}

    @component.operation('create', access='write')
    def create_note(title, body=''):
        if not isinstance(title, str) or not title.strip():
            raise ValueError('title must be nonempty text')
        key = str(len(notes) + 1)
        notes[key] = {'id': key, 'title': title, 'body': body}
        return dict(notes[key])

    @component.operation('get')
    def get_note(id):
        return dict(notes[id])

    @component.operation('list')
    def list_notes():
        return [dict(note) for note in notes.values()]

    return component


if __name__ == '__main__':
    create().run()
