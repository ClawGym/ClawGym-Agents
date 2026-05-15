(function() {
  'use strict';
  angular.module('demoApp').directive('btnGroup', function() {
    return {
      restrict: 'A',
      templateUrl: 'app/templates/buttons.html'
    };
  });
})();
