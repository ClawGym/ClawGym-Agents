import React from 'react';
import ReactDOM from 'react-dom';

export default class OldClassComponent extends React.Component {
  constructor(props) {
    super(props);
    this.state = { n: 0 };
  }
  componentWillMount() {
    console.log('will mount');
  }
  componentWillReceiveProps(nextProps) {
    console.log('will receive', nextProps);
  }
  render() {
    const node = ReactDOM.findDOMNode(this);
    return (
      <div ref="legacyRef">
        Legacy: {this.state.n} {node ? '' : ''}
      </div>
    );
  }
}
