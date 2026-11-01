import QtQuick
import QtQuick.Controls
Rectangle {
    objectName: 'counterView'
    color: '#edf3fa'
    implicitWidth: 300
    implicitHeight: 190
    radius: 16
    Column {
        anchors.centerIn: parent
        spacing: 16
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: '计数器'
            textFormat: Text.PlainText
            color: '#1d3653'
            font.pixelSize: 18
        }
        Text {
            objectName: 'counterValue'
            anchors.horizontalCenter: parent.horizontalCenter
            text: counterModel.value
            color: '#213b61'
            font.pixelSize: 32
        }
        Text {
            objectName: 'counterError'
            width: 260; wrapMode: Text.Wrap; textFormat: Text.PlainText
            text: counterModel.lastError; color: '#a23445'; visible: text.length > 0
        }
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 18
            Button { objectName: 'counterDecrease'; text: '−'; onClicked: counterModel.decrease() }
            Button { objectName: 'counterIncrease'; text: '+'; onClicked: counterModel.increase() }
        }
    }
}
